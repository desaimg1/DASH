import json
from pathlib import Path
from pprint import pprint
import time
import pytest
import sys
sys.path.append("../../utils")
import snappi_utils as su

current_file_dir = Path(__file__).parent

"""
This covers following scenario :

Test vnet to vnet communication with ACL on outbound direction:
1. Configure DPU to deny and allow traffic
2. Configure TGEN traffic flow as one vnet to another vnet of two ixia-c ports
3. Verify Traffic denied through deny traffic IPs

Topology Used :

       --------          -------          -------- 
      |        |        |       |        |        |
      |        |        |       |        |        |
      |  TGEN  |--------|  DPU  |--------|  TGEN  |
      |        |        |       |        |        |
      |        |        |       |        |        |
       --------          -------          -------- 
       
"""

###############################################################
#                  Declaring Global variables
###############################################################
SPEED = "SPEED_100_GBPS"
TOTALPACKETS = 100
PPS = 10
TRAFFIC_SLEEP_TIME = (TOTALPACKETS / PPS) + 2 
PACKET_LENGTH = 128
ENI_IP = "1.1.0.1"
NETWORK_IP2 = "1.128.0.2"
NETWORK_IP1 = "1.140.0.2"

DPU_VTEP_IP = "221.0.0.2"
ENI_VTEP_IP = "221.0.1.11"
NETWORK_VTEP_IP = "221.0.2.101"

###############################################################
#                  Start of the testcase
###############################################################

class TestAclOutbound:

    @pytest.fixture(scope="class")
    def setup_config(self):
        """
        Fixture returns the content of the file with SAI configuration commands.
        scope=class - The file is loaded once for the whole test class
        """
        current_file_dir = Path(__file__).parent
        with (current_file_dir / 'config_outbound_setup_commands.json').open(mode='r') as config_file:
            setup_commands = json.load(config_file)
        return setup_commands

    def test_setup(self, dpu, setup_config):
        results = [*dpu.process_commands(setup_config)]
        print("\n======= SAI setup commands RETURN values =======")
        pprint(results)
        assert all(results), "Setup error"

    def test_vm_to_vm_commn_acl_outbound(self, dataplane):

        # Configure TGEN
        # configure L1 properties on configured ports
        # su.config_l1_properties(dataplane, SPEED)
        
        # Flow1 settings
        f1 = dataplane.configuration.flows.flow(name="OUTBOUND")[-1]
        f1.tx_rx.port.tx_name = dataplane.configuration.ports[0].name
        f1.tx_rx.port.rx_name = dataplane.configuration.ports[1].name
        f1.size.fixed = PACKET_LENGTH
        # send n packets and stop
        f1.duration.fixed_packets.packets = TOTALPACKETS
        # send n packets per second
        f1.rate.pps = PPS
        f1.metrics.enable = True

        outer_eth1, ip1, udp1, vxlan1, inner_eth1, inner_ip1, inner_udp1= (
                f1.packet.ethernet().ipv4().udp().vxlan().ethernet().ipv4().udp()
        )

        outer_eth1.src.value = "80:09:02:01:00:01"
        outer_eth1.dst.value = "c8:2c:2b:00:d1:30"
        outer_eth1.ether_type.value = 2048

        ip1.src.value = ENI_VTEP_IP #ENI - VTEP
        ip1.dst.value = DPU_VTEP_IP #DPU - VTEP

        udp1.src_port.value = 11638
        udp1.dst_port.value = 4789

        #vxlan.flags.value = 
        vxlan1.vni.value = 11
        vxlan1.reserved0.value = 0
        vxlan1.reserved1.value = 0

        inner_eth1.src.value = "00:1A:C5:00:00:01"
        inner_eth1.dst.value = "00:1b:6e:14:00:02"
        inner_ip1.src.value = ENI_IP   #ENI
        inner_ip1.dst.value = NETWORK_IP1  #world

        inner_udp1.src_port.value = 10000
        inner_udp1.dst_port.value = 20000

        dataplane.set_config()

        # Verify traffic
        su.start_traffic(dataplane, f1.name)
        time.sleep(TRAFFIC_SLEEP_TIME)            
        dataplane.stop_traffic()

        #Packets should be denied
        acl_traffic_result = su.check_flow_tx_rx_frames_stats(dataplane, f1.name)
        print("Traffic Result : {}".format(acl_traffic_result))

        dataplane.tearDown()

        # Validate test result
        assert acl_traffic_result==False, "Traffic test Deny failure"   

    def test_cleanup(self, dpu, setup_config):
        cleanup_commands = [{'name' : cmd['name'] ,'op': 'remove'} for cmd in setup_config]
        cleanup_commands = reversed(cleanup_commands)
        results = [*dpu.process_commands(cleanup_commands)]
        print("\n======= SAI teardown commands RETURN values =======")
        pprint(results)
        assert all([x==0 for x in results]), "Teardown Error"
