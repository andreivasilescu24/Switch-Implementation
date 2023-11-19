#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

root_bridge_id = -1

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bpdu_packet(root_bridge_id, root_path_cost, bridge_id, mac_bpdu, switch_mac):
    ethernet_part =  struct.pack('!6s6sH', mac_bpdu, switch_mac, 0x000F)
    logical_link_control_part = struct.pack('!BBB', 0x42, 0x42, 0x03)
    bpdu_header = struct.pack('!HBB', 0x0000, 0x00, 0x00)
    bpdu_payload = struct.pack('!HIH', root_bridge_id, root_path_cost, bridge_id)
    
    bpdu = ethernet_part + logical_link_control_part + bpdu_header + bpdu_payload

    return bpdu

def send_bdpu_every_sec(switch_interfaces, bridge_id, mac_bpdu, switch_mac):
    while True:
        # TODO Send BDPU every second if necessary
        if bridge_id == root_bridge_id:
            for port, port_type in switch_interfaces.items():
                if port_type == -1:
                    bpdu_packet = create_bpdu_packet(root_bridge_id, 0, bridge_id, mac_bpdu, switch_mac)
                    send_to_link(port, bpdu_packet, len(bpdu_packet))
        time.sleep(1)

def isUnicast(mac):
    return (mac[0] & 0x01) == 0
        
def is_vlan_tag_needed(switch_interfaces, interface_send, vlan_id):
    if switch_interfaces[interface_send] == -1:
        return True
    elif switch_interfaces[interface_send] != -1 and vlan_id == switch_interfaces[interface_send]:
        return False
    

def send_vlan_packets(switch_interfaces, interface_received, interface_send, data, length, vlan_id):
    if switch_interfaces[interface_received] == -1:
        if is_vlan_tag_needed(switch_interfaces, interface_send, vlan_id):
            send_to_link(interface_send, data, length)
        else:
            send_to_link(interface_send, data[0:12] + data[16:], length - 4)
    else:
        if is_vlan_tag_needed(switch_interfaces, interface_send, switch_interfaces[interface_received]):
            send_to_link(interface_send, data[0:12] + create_vlan_tag(switch_interfaces[interface_received]) + data[12:], length + 4)
        else:
            send_to_link(interface_send, data, length)


def is_vlan_compatible(interface_received, interface_send, switch_interfaces, vlan_id):
    if switch_interfaces[interface_received] == -1 and (switch_interfaces[interface_send] == -1 or switch_interfaces[interface_send] == vlan_id):
        return True
    elif switch_interfaces[interface_send] == -1:
        return True
    elif switch_interfaces[interface_received] == switch_interfaces[interface_send]:
        return True
    else:
        return False

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]

    Table = {}
    switch_interfaces = {}
    port_states = {}

    config_file_path = "configs/switch" + switch_id + ".cfg"
    config_file = open(config_file_path, "r")

    # STP necessary
    bridge_id = int(config_file.readline())
    global root_bridge_id
    root_bridge_id = bridge_id
    root_path_cost = 0
    mac_bpdu = b'\x01\x80\xc2\x00\x00\x00'

    port_details = config_file.readlines()

    port_index = 0
    for config_file_line in port_details:
        config_file_line = config_file_line.strip().split(" ")
        if config_file_line[1] == "T":
            switch_interfaces[port_index] = -1 
            port_states[port_index] = "BLOCKING"
        else: 
            switch_interfaces[port_index] = int(config_file_line[1])
            port_states[port_index] = "LISTENING"
        port_index += 1

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    if bridge_id == root_bridge_id:
        for port, port_type in switch_interfaces.items():
            if port_type == -1:
                port_states[port] = "LISTENING"

    # Create and start a new thread that deals with sending BDPU
    switch_mac = get_switch_mac()
    t = threading.Thread(target=send_bdpu_every_sec, args=(switch_interfaces, bridge_id, mac_bpdu, switch_mac))
    t.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))
    
    root_port = -1
    
    while True:
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        if dest_mac == mac_bpdu:
            bdpu_payload = struct.unpack('!HIH', data[21:29])
            root_bridge_id_bpdu = bdpu_payload[0]
            root_path_cost_bpdu = bdpu_payload[1]
            bridge_id_bpdu = bdpu_payload[2]

            if root_bridge_id_bpdu < root_bridge_id:
                ex_root_bridge_id = root_bridge_id
                root_bridge_id = root_bridge_id_bpdu
                root_path_cost = root_path_cost_bpdu + 10
                root_port = interface

                if ex_root_bridge_id == bridge_id:
                    for port, port_type in switch_interfaces.items():
                        if port_type == -1:
                            port_states[port] = "BLOCKING"

                if port_states[root_port] == "BLOCKING":
                    port_states[root_port] = "LISTENING"
                
                bpdu_packet = create_bpdu_packet(root_bridge_id, root_path_cost, bridge_id, mac_bpdu, switch_mac)
                for port, port_type in switch_interfaces.items():
                    if port_type == -1 and port != root_port:
                        send_to_link(port, bpdu_packet, len(bpdu_packet))
            
            elif root_bridge_id_bpdu == root_bridge_id:
                if interface == root_port and root_path_cost_bpdu + 10 < root_path_cost:
                    root_path_cost = root_path_cost_bpdu + 10
                elif interface != root_port:
                    if root_path_cost_bpdu > root_path_cost:
                        if port_states[interface] == "BLOCKING":
                            port_states[interface] = "LISTENING"

            elif bridge_id_bpdu == bridge_id:
                port_states[interface] = "BLOCKING"
            else:
                continue
            
            if bridge_id == root_bridge_id:
                for port, port_type in port_states.items():
                    port_states[port] = "LISTENING"
        
        elif port_states[interface] == "LISTENING":

            print(f'Destination MAC: {dest_mac}')
            print(f'Source MAC: {src_mac}')
            print(f'EtherType: {ethertype}')

            print("Received frame of size {} on interface {}".format(length, interface), flush=True)

            # TODO: Implement forwarding with learning
            Table[src_mac] = interface
            if isUnicast(dest_mac):
                if dest_mac in Table:
                    if port_states[Table[dest_mac]] == 'LISTENING' and is_vlan_compatible(interface, Table[dest_mac], switch_interfaces, vlan_id):
                        send_vlan_packets(switch_interfaces, interface, Table[dest_mac], data, length, vlan_id)
                else:
                    for curr_interface in interfaces:
                        if curr_interface != interface:
                            if port_states[curr_interface] == 'LISTENING' and is_vlan_compatible(interface, curr_interface, switch_interfaces, vlan_id):
                                send_vlan_packets(switch_interfaces, interface, curr_interface, data, length, vlan_id)
            else:
                for curr_interface in interfaces:
                    if curr_interface != interface:
                        if port_states[curr_interface] == 'LISTENING' and is_vlan_compatible(interface, curr_interface, switch_interfaces, vlan_id):
                            send_vlan_packets(switch_interfaces, interface, curr_interface, data, length, vlan_id)

if __name__ == "__main__":
    main()
