# Switch Implementation

## Running

```bash
sudo python3 checker/topo.py
```

This will open 9 terminals, 6 hosts and 3 for the switches. On the switch terminal you will run

```bash
make run_switch SWITCH_ID=X # X is 0,1 or 2
```

The hosts have the following IP addresses.

```
host0 192.168.1.1
host1 192.168.1.2
host2 192.168.1.3
host3 192.168.1.4
host4 192.168.1.5
host5 192.168.1.6
```

We will be testing using the ICMP. For example, from host0 we will run:

```
ping 192.168.1.2
```

Note: We will use wireshark for debugging. From any terminal you can run `wireshark&`.

### **create_bpdu_packet**

In this function, I create the BPDU packet, which will contain the Ethernet part, including the destination MAC address specific to BPDU (01:80:C2:00:00:00), the source MAC address (the switch's MAC address), and a field for `LLC_LENGTH`, which in my case is 15 bytes (described below in the frame structure). Then, I include the LLC Header, which is made up of 3 bytes: 0x42, 0x42, and 0x03, as specified. Additionally, I place the BPDU Header in the packet, which is composed of 4 bytes, all set to 0, followed by the BPDU payload, which contains the Root Bridge ID (2 bytes), the Root Path Cost (4 bytes), and the Bridge ID (2 bytes). Therefore, the total LLC_LENGTH will be 3 + 4 + 8 = 15 bytes. All these parts of the final packet are created using `struct.pack`, and the byte strings are then concatenated in the correct order to form the final BPDU packet, which is returned.

### **send_bdpu_every_sec**

This function is called by a thread that sends BPDU packets. It will keep sending these packets as long as the switch considers itself to be the Root Bridge, at one-second intervals. The packets are sent on all trunk ports of the switch, with the Root Path Cost set to 0 because every switch considers itself to be the Root Bridge while it is sending these packets.

### **isUnicast**

If the least significant bit of the MAC address is set, the address is a multicast address and will return `False`. Otherwise, it is a unicast address and will return `True`.

### **is_vlan_tag_needed**

This function checks if a VLAN tag is needed in the packet to be sent. It verifies whether the interface through which the packet will be sent is a trunk port (where a tag is added) or an access port, and whether the VLAN matches the VLAN on which the packet was received (in which case no tag is added).

### **send_vlan_packets**

This function sends packets with or without a VLAN tag, depending on the situation. If the packet is received on a trunk port, it will check if a VLAN tag needs to be added based on the interface through which it will be sent. If the tag is needed, the packet is sent as is because it already has the tag from the trunk. If no tag is needed, it removes the tag from the packet by reducing the packet length by 4 bytes (the size of the tag). If the packet was received on an access port and a tag is required, the function will add the VLAN tag using the `create_vlan_tag` function and increase the packet length by 4 bytes. If no tag is required, the packet is sent exactly as it was received.

### **is_vlan_compatible**

This function checks if a packet is compatible with a given interface based on the type of port and the VLAN of the received packet. A packet is compatible with the interface if:

- The packet was received on a trunk port and is being sent on another trunk port or on an access port that matches the VLAN of the packet.
- The packet is being sent on a trunk port.
- The packet was received on an access port with a VLAN that matches the VLAN of the access port through which the packet should be sent.

If none of these conditions are met, the packet is incompatible and will not be forwarded on that interface.

---

### **Initial Setup**

First, I create three dictionaries:

- **"Table"**: represents the CAM table of the switch.
- **"switch_interfaces"**: maps the interface index (read from the configuration file for the switch) to the type of port (VLAN or Trunk).
- **"port_states"**: holds the state of each interface (LISTENING/BLOCKING).

Next, I read the bridge ID and port type lines from the switch's configuration file, filling in the **"switch_interfaces"** and **"port_states"** dictionaries. As I parse the lines, I increment an index for the interfaces and populate the **"switch_interfaces"** dictionary with the interface index as keys and port types (VLAN or -1 for Trunk) as values. The **"port_states"** dictionary has the same keys as **"switch_interfaces"**, with values initialized to either "BLOCKING" for Trunk ports or "LISTENING" for other ports. I then set all Trunk ports to "LISTENING" if the `bridge_id` equals the `root_bridge_id`, since at the start of STP, each switch assumes it is the Root Bridge. A thread is also started to send BPDU packets every second as long as the switch still considers itself the Root Bridge, using the `send_bdpu_every_sec` function (eventually, only the Root Bridge will send BPDU packets). A global variable is used to store the Root Bridge ID so that it is accessible in both the `main` function and the `send_bdpu_every_sec` thread.

---

### **Main Loop**

After all the initializations, the switch enters a loop to receive packets. If a received packet is a BPDU (destination MAC address is 01:80:C2:00:00:00), the function will extract the Root Bridge ID, Root Path Cost, and Bridge ID from the packet using `struct.unpack`. The Root Bridge ID and Bridge ID will be `SHORT` types, and the Root Path Cost will be an `INT`.

According to the pseudocode in the prompt, the first step is to check if the received Root Bridge ID is smaller than the currently stored Root Bridge ID. If this condition is met, the Root Bridge ID is updated to the new one received in the packet, the Root Path Cost is increased by 10 (the cost of the link), and the Root Port is updated to the interface on which the packet was received.

If the switch considers itself the Root Bridge before receiving the packet, all its Trunk ports are set to "BLOCKING", and the Root Port is set to "LISTENING". A new BPDU packet is then created with the updated Root Bridge ID and Root Path Cost and sent to all the switch's Trunk ports, excluding the Root Port.

If the received BPDU is from the current Root Bridge, it checks if the packet was received on the Root Port. If so, and if the Root Path Cost received plus an additional 10 (cost of the link) is smaller than the current Root Path Cost, the value is updated with the new Root Path Cost + 10.

If the packet wasn't received on the Root Port and the Root Path Cost received is larger than the current one, the port's state is set to "LISTENING" (if it wasn't already). If the packet's Bridge ID matches the switch's Bridge ID, the interface on which the packet was received is set to "BLOCKING" to avoid loops. If none of these conditions are met, the packet is discarded.

Additionally, if after these checks the switch is still the Root Bridge, all of its ports are set to "LISTENING".

If the received packet is not a BPDU and the interface it was received on is in the "LISTENING" state, the switch will add an entry to the CAM table with the source MAC address of the packet and the interface on which it was received.

If the packet is unicast and the destination MAC address is in the CAM table, the function checks if the interface through which it should be sent is "LISTENING" and whether the VLAN is compatible. If both conditions are met, the packet is forwarded. If the destination MAC address is not in the CAM table, the packet is sent on all "LISTENING" interfaces that are compatible with the VLAN, except for the one on which the packet was received. For multicast packets, the same algorithm is applied—sending the packet to all "LISTENING" interfaces compatible with the VLAN, excluding the interface on which it was received.
