import json
from pathlib import Path
from pprint import pprint
import time
import pytest
import sys
sys.path.append("../utils")
import snappi_utils as su
import common_utils as cu

current_file_dir = Path(__file__).parent

"""
This covers following scenario :
vnet to vnet communication with UDP traffic flow with 8 ENIS and 3k IPs respectively:
Configure DUT 
Configure TGEN UDP traffic flow as one vnet to another vnet of two OpenTrafficGenerator ports
Verify Traffic flow between vnet to vnet through DPU  

       
"""

###############################################################
#                  Declaring Global variables
###############################################################

SPEED = "SPEED_100_GBPS"
ENI_IP = "1.1.0.1"
NETWORK_IP1 = "1.128.0.1"
NETWORK_IP_DENY = "1.128.1.1"

DPU_VTEP_IP = "221.0.0.2"
ENI_VTEP_IP = "221.0.1.11"
NETWORK_VTEP_IP = "221.0.2.101"
TOTAL_FLOWS = 8
NO_OF_IPS_ON_EACH_FLOW = 3000
eniIps = cu.create_ip_list(ENI_IP, TOTAL_FLOWS, mask=16)
networkIps = cu.create_ip_list(NETWORK_IP1, TOTAL_FLOWS, mask=16, incr = 4)

BGP_TYPE = "ebgp"
NUMBER_OF_ROUTES = 8
BGP_AS_NUMBER = 200
TOTALPACKETS = NO_OF_IPS_ON_EACH_FLOW * 5
PPS = 1000
TRAFFIC_SLEEP_TIME = (TOTALPACKETS / PPS) + 2


###############################################################
#                  Start of the testcase
###############################################################

@pytest.fixture(scope="class")
def dp(request, dataplane_cls):
    dataplane_cls.configuration.devices.device(name='Topology 1')
    dataplane_cls.configuration.devices.device(name='Topology 2')
    eth = dataplane_cls.configuration.devices[0].ethernets.add()
    eth.port_name = dataplane_cls.configuration.ports[0].name
    eth.name = 'Ethernet 1'
    eth.mac = "80:09:02:01:00:01"
    ipv4 = eth.ipv4_addresses.add()
    ipv4.name = 'IPv4 1'
    ipv4.address = '220.0.1.2'
    ipv4.gateway = '220.0.1.1'
    ipv4.prefix = 24
    bgpv4 = dataplane_cls.configuration.devices[0].bgp
    bgpv4.router_id = '220.0.1.1'
    bgpv4_int = bgpv4.ipv4_interfaces.add()
    bgpv4_int.ipv4_name = ipv4.name
    bgpv4_peer = bgpv4_int.peers.add()
    bgpv4_peer.name = 'BGP 1' 
    bgpv4_peer.as_type = BGP_TYPE
    bgpv4_peer.peer_address = '220.0.1.1'
    bgpv4_peer.as_number = BGP_AS_NUMBER
    route_range = bgpv4_peer.v4_routes.add(name="Network_Group1") 
    route_range.addresses.add(address='221.0.1.1', prefix=32, count=NUMBER_OF_ROUTES)

    ## Rx side 
    eth = dataplane_cls.configuration.devices[1].ethernets.add()
    eth.port_name = dataplane_cls.configuration.ports[1].name
    eth.name = 'Ethernet 2'
    eth.mac = "80:09:02:01:00:03"
    ipv4 = eth.ipv4_addresses.add()
    ipv4.name = 'IPv4 2'
    ipv4.address = '220.0.1.1'
    ipv4.gateway = '220.0.1.2'
    ipv4.prefix = 24
    bgpv4 = dataplane_cls.configuration.devices[1].bgp
    bgpv4.router_id = '220.0.1.1'
    bgpv4_int = bgpv4.ipv4_interfaces.add()
    bgpv4_int.ipv4_name = ipv4.name
    bgpv4_peer = bgpv4_int.peers.add()
    bgpv4_peer.name = 'BGP 2' 
    bgpv4_peer.as_type = BGP_TYPE
    bgpv4_peer.peer_address = '220.0.1.2'
    bgpv4_peer.as_number = 100
    route_range = bgpv4_peer.v4_routes.add(name="Network_Group2") 
    route_range.addresses.add(address='221.0.2.101', prefix=32, count=NUMBER_OF_ROUTES)

    # Flow1 settings
    for i in range (1, TOTAL_FLOWS+1):
        f1 = dataplane_cls.configuration.flows.flow(name="ENI_TO_NETWORK" + str(i))[-1]
        f1.tx_rx.port.tx_name = dataplane_cls.configuration.ports[0].name
        f1.tx_rx.port.rx_name = dataplane_cls.configuration.ports[1].name
        f1.size.fixed = 128
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

        #inner_eth1.src.value = "00:1A:C5:00:00:01"
        if len(str(hex((i-1)*30).split('0x')[1])) == 1:
            m = '0'+hex((i-1)*30).split('0x')[1]
        else:
            m = hex((i-1)*30).split('0x')[1]

        inner_eth1.src.value = "00:1A:C5:%s:00:01"%m
        inner_eth1.dst.increment.start = "00:1b:6e:18:00:01"
        inner_eth1.dst.increment.step = "00:00:00:00:00:02"
        inner_eth1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_ip1.src.value = eniIps[i-1]   #ENI
        inner_ip1.dst.increment.start = NETWORK_IP1  #world
        inner_ip1.dst.increment.step = '0.0.2.0'  #world
        inner_ip1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_udp1.src_port.value = 10000
        inner_udp1.dst_port.value = 20000

    dataplane_cls.set_config()
    dataplane_cls.start_protocols()
    time.sleep(10)
    request.cls.dp = dataplane_cls

@pytest.mark.usefixtures("dp")
class TestHero:

    def test_ping(self):
        assert self.dp.check_ping('IPv4 1', '220.0.1.1'), "ping from TGEN to DUT failed"
        assert self.dp.check_ping('IPv4 2', '220.0.2.1'), "ping from TGEN to DUT failed"


    def test_bgp_neighborship(self):
        assert su.check_bgp_neighborship_established(dp), "Verify BGP neighbourship failure" 


    def test_bgp_routes_advertised(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["routes_advertised"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert int(r.routes_advertised) == NUMBER_OF_ROUTES, "Verify BGP routes advertised count"


    def test_bgp_routes_received(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["routes_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.routes_received == NUMBER_OF_ROUTES, "Verify BGP routes received count"


    def test_bgp_routes_withdraw_sent(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["route_withdraws_sent"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.route_withdraws_sent == 0, "Verify BGP routes withdraw count"


    def test_bgp_routes_withdraw_received(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["route_withdraws_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.route_withdraws_received == 0


    def test_bgp_routes_updates_sent(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["updates_sent"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.updates_sent == 1


    def test_bgp_routes_updates_received(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["updates_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.updates_received == 1


    def test_bgp_routes_opens_sent(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["opens_sent"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.opens_sent >= 1


    def test_bgp_routes_opens_sent(self):
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["opens_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.opens_received == 1


    def test_bgp_routes_keepalives_sent(self):
        time.sleep(30)
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["keepalives_sent"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.keepalives_sent >= 1


    def test_bgp_routes_keepalives_received(self):
        time.sleep(30)
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["keepalives_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.keepalives_received >= 1


    def test_bgp_routes_notifications_sent(self):
        self.dp.stop_protocols()
        time.sleep(5)
        self.dp.start_protocols()
        time.sleep(5)
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["notifications_sent"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.notifications_sent >= 1

    def test_bgp_routes_notifications_received(self):
        self.dp.stop_protocols()
        time.sleep(5)
        self.dp.start_protocols()
        time.sleep(5)
        req =self.dp.api.metrics_request()
        req.bgpv4.column_names = ["notifications_received"]
        results = self.dp.api.get_metrics(req)
        for r in results.bgpv4_metrics:
            print(r)
            assert r.notifications_received >= 1

    def capture_start_stop(self):
        self.dp.stop_protocols()
        self.dp.start_capture()
        time.sleep(5)
        self.dp.start_protocols()
        time.sleep(5)
        self.dp.stop_capture()

    def test_traffic_stats(self):
        self.dp.start_traffic()
        time.sleep(TRAFFIC_SLEEP_TIME)            
        self.dp.stop_traffic()
        flow_names = [f.name for f in self.dp.configuration.flows]
        for flow in flow_names:
            assert self.dp.check_flow_tx_rx_frames_stats(flow.name) == False

    @pytest.mark.parametrize("PACKET_LENGTH", [256, 512, 1024, 1512, 9000])
    def test_traffic_stats_with_different_pkt_length(self, PACKET_LENGTH):
        f = self.dp.configuration.flows[0]
        f.size.fixed = PACKET_LENGTH
        self.dp.set_config()

        self.dp.start_traffic(f.name)
        time.sleep(TRAFFIC_SLEEP_TIME)           
        self.dp.stop_traffic(f.name)

        f = self.dp.configuration.flows[0]
        f.size.fixed = 128
        self.dp.set_config()

        assert self.dp.check_flow_tx_rx_frames_stats(f.name) == False


    def test_deny_ip_failed(self):
        f1 = dataplane_cls.configuration.flows.flow(name="ENI_TO_NETWORK_DENY")[-1]
        f1.tx_rx.port.tx_name = dataplane_cls.configuration.ports[0].name
        f1.tx_rx.port.rx_name = dataplane_cls.configuration.ports[1].name
        f1.size.fixed = 128
        # send 1000 packets and stop
        f1.duration.fixed_packets.packets = TOTALPACKETS
        # send 1000 packets per second
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

        #inner_eth1.src.value = "00:1A:C5:00:00:01"
        if len(str(hex((i-1)*30).split('0x')[1])) == 1:
            m = '0'+hex((i-1)*30).split('0x')[1]
        else:
            m = hex((i-1)*30).split('0x')[1]

        inner_eth1.src.value = "00:1A:C5:%s:00:01"%m
        inner_eth1.dst.increment.start = "00:1b:6e:18:00:01"
        inner_eth1.dst.increment.step = "00:00:00:00:00:02"
        inner_eth1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_ip1.src.value = eniIps[i-1]   #ENI
        inner_ip1.dst.increment.start = NETWORK_IP_DENY  #world
        inner_ip1.dst.increment.step = '0.0.2.0'  #world
        inner_ip1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_udp1.src_port.value = 10000
        inner_udp1.dst_port.value = 20000

        dataplane_cls.set_config()

        self.dp.start_traffic(f1.name)
        time.sleep(TRAFFIC_SLEEP_TIME)
        self.dp.stop_traffic(f1.name)
        val = self.dp.check_flow_tx_rx_frames_stats(f1.name)
        f1.enable = False
        assert  val == True

    def test_allow_ip_with_different_mac(self):
        f1 = dataplane_cls.configuration.flows.flow(name="ENI_TO_NETWORK_DENY")[-1]
        f1.tx_rx.port.tx_name = dataplane_cls.configuration.ports[0].name
        f1.tx_rx.port.rx_name = dataplane_cls.configuration.ports[1].name
        f1.size.fixed = 128
        # send 1000 packets and stop
        f1.duration.fixed_packets.packets = TOTALPACKETS
        # send 1000 packets per second
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

        #inner_eth1.src.value = "00:1A:C5:00:00:01"
        if len(str(hex((i-1)*30).split('0x')[1])) == 1:
            m = '0'+hex((i-1)*30).split('0x')[1]
        else:
            m = hex((i-1)*30).split('0x')[1]

        inner_eth1.src.value = "00:00:00:%s:00:01"%m
        inner_eth1.dst.increment.start = "00:1b:6e:18:00:01"
        inner_eth1.dst.increment.step = "00:00:00:00:00:02"
        inner_eth1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_ip1.src.value = eniIps[i-1]   #ENI
        inner_ip1.dst.increment.start = NETWORK_IP1  #world
        inner_ip1.dst.increment.step = '0.0.2.0'  #world
        inner_ip1.dst.increment.count = NO_OF_IPS_ON_EACH_FLOW

        inner_udp1.src_port.value = 10000
        inner_udp1.dst_port.value = 20000

        dataplane_cls.set_config()

        self.dp.start_traffic(f1.name)
        time.sleep(TRAFFIC_SLEEP_TIME)
        self.dp.stop_traffic(f1.name)
        val = self.dp.check_flow_tx_rx_frames_stats(f1.name)
        f1.enable = False
        assert  val == True

    def test_calculate_latency(self):
        for f in self.dp.configuration.flows:
            f.metrics.latency.enable = True
            f.metrics.latency.mode = f.metrics.latency.STORE_FORWARD
        self.dp.set_config()

        self.dp.start_traffic()
        time.sleep(TRAFFIC_SLEEP_TIME)
        self.dp.stop_traffic()

        flow_names = [f.name for f in self.dp.configuration.flows]
        for flow in flow_names:
            req = self.api.metrics_request()
            req.flow.flow_names = [flow]
            flow_stats = self.api.get_metrics(req)
            latency = sum([m.latency for m in flow_stats.flow_metrics])