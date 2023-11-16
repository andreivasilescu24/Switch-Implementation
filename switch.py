#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

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

def send_bdpu_every_sec():
    while True:
        # TODO Send BDPU every second if necessary
        time.sleep(1)

def isUnicast(mac):
    return mac[0] & 0x80

# def is_vlan_tag_needed_trunk(switch_interfaces, interface_send, vlan_id):
#     if switch_interfaces[interface_send] == -1:
#         return True
#     elif switch_interfaces[interface_send] != -1 and vlan_id == switch_interfaces[interface_send]:
#         return False
    
        
def is_vlan_tag_needed(switch_interfaces, interface_send, vlan_id):
    if switch_interfaces[interface_send] == -1:
        return True
    elif switch_interfaces[interface_send] != -1 and vlan_id == switch_interfaces[interface_send]:
        return False
    

def send_vlan_packets(switch_interfaces, interface_received, interface_send, data, length, vlan_id):
    print(interface_received)
    print(interface_send)
    if switch_interfaces[interface_received] == -1:
        if is_vlan_tag_needed(switch_interfaces, interface_send, vlan_id):
            send_to_link(interface_send, data, length)
        else:
            print("********** TRUNK TO ACCESS **********")
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
    switch_interfaces = {}

    config_file_path = "configs/switch" + switch_id + ".cfg"
    config_file = open(config_file_path, "r")

    priority = int(config_file.readline())
    port_details = config_file.readlines()

    port_index = 0
    for config_file_line in port_details:
        config_file_line = config_file_line.strip().split(" ")
        if config_file_line[1] == "T":
            switch_interfaces[port_index] = -1 
        else: 
            switch_interfaces[port_index] = int(config_file_line[1])
        port_index += 1

    print(switch_interfaces)

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))

    Table = {}

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # Print the MAC src and MAC dst in human readable format
        # dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        # src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        
        print("VLAN ID {vlan_id}".format(vlan_id=vlan_id))

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        # TODO: Implement forwarding with learning
        Table[src_mac] = interface
        if isUnicast(dest_mac):
            if dest_mac in Table:
                if is_vlan_compatible(interface, Table[dest_mac], switch_interfaces, vlan_id):
                    send_vlan_packets(switch_interfaces, interface, Table[dest_mac], data, length, vlan_id)
            else:
                for curr_interface in interfaces:
                    if curr_interface != interface:
                        if is_vlan_compatible(interface, curr_interface, switch_interfaces, vlan_id):
                            send_vlan_packets(switch_interfaces, interface, curr_interface, data, length, vlan_id)
        else:
            # trimite cadrul pe toate celelalte porturi
            for curr_interface in interfaces:
                if curr_interface != interface:
                    if is_vlan_compatible(interface, curr_interface, switch_interfaces, vlan_id):
                        send_vlan_packets(switch_interfaces, interface, curr_interface, data, length, vlan_id)

        # TODO: Implement VLAN support


        # TODO: Implement STP support


if __name__ == "__main__":
    main()
