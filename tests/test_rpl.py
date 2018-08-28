"""
Tests for SimEngine.Mote.rpl
"""

import types

import pytest

import test_utils as u
import SimEngine.Mote.MoteDefines as d
import SimEngine.Mote.rpl as rpl

@pytest.fixture(params=['FullyMeshed','Linear'])
def fixture_conn_class(request):
    return request.param

def test_ranks_forced_state(sim_engine,fixture_conn_class):
    '''
    Verify the force_initial_routing_and_scheduling_state option
    create the expected RPL state.
    '''

    sim_engine = sim_engine(
        {
            'exec_numMotes': 3,
            'conn_class':    fixture_conn_class,
        },
        force_initial_routing_and_scheduling_state = True
    )

    root = sim_engine.motes[0]
    hop1 = sim_engine.motes[1]
    hop2 = sim_engine.motes[2]

    assert root.dagRoot is True
    assert root.rpl.getPreferredParent()      ==    None
    assert root.rpl.get_rank()                ==     256
    assert root.rpl.getDagRank()              ==       1

    assert hop1.dagRoot is False
    assert hop1.rpl.getPreferredParent()      == root.get_mac_addr()
    assert hop1.rpl.get_rank()                ==     768
    assert hop1.rpl.getDagRank()              ==       3

    if   fixture_conn_class=='FullyMeshed':
        assert hop2.dagRoot is False
        assert hop2.rpl.getPreferredParent()  == root.get_mac_addr()
        assert hop2.rpl.get_rank()            ==     768
        assert hop2.rpl.getDagRank()          ==       3
    elif fixture_conn_class=='Linear':
        assert hop2.dagRoot is False
        assert hop2.rpl.getPreferredParent()  == hop1.get_mac_addr()
        assert hop2.rpl.get_rank()            ==    1280
        assert hop2.rpl.getDagRank()          ==       5
    else:
        raise SystemError()

def test_source_route_calculation(sim_engine):

    sim_engine = sim_engine(
        {
            'exec_numMotes':      8,
        },
    )

    addr = []

    for i in range(8):
        sim_engine.motes[i].add_ipv6_prefix(d.IPV6_DEFAULT_PREFIX)
        addr.append(sim_engine.motes[i].get_ipv6_global_addr())

    root = sim_engine.motes[0]

    # assume DAOs have been receuved by all mote in this topology
    '''          4----5
                /
       0 ----- 1 ------ 2 ----- 3  NODAO  6 ---- 7
    '''
    root.rpl.addParentChildfromDAOs(parent_addr=addr[0], child_addr=addr[1])
    root.rpl.addParentChildfromDAOs(parent_addr=addr[1], child_addr=addr[4])
    root.rpl.addParentChildfromDAOs(parent_addr=addr[4], child_addr=addr[5])
    root.rpl.addParentChildfromDAOs(parent_addr=addr[1], child_addr=addr[2])
    root.rpl.addParentChildfromDAOs(parent_addr=addr[2], child_addr=addr[3])
    # no DAO received for 6->3 link
    root.rpl.addParentChildfromDAOs(parent_addr=addr[6], child_addr=addr[7])

    # verify all source routes
    assert root.rpl.computeSourceRoute(addr[1]) == [addr[1]]
    assert root.rpl.computeSourceRoute(addr[2]) == [addr[1], addr[2]]
    assert root.rpl.computeSourceRoute(addr[3]) == [addr[1], addr[2], addr[3]]
    assert root.rpl.computeSourceRoute(addr[4]) == [addr[1], addr[4]]
    assert root.rpl.computeSourceRoute(addr[5]) == [addr[1], addr[4], addr[5]]
    assert root.rpl.computeSourceRoute(addr[6]) == None
    assert root.rpl.computeSourceRoute(addr[7]) == None


def test_upstream_routing(sim_engine):
    sim_engine = sim_engine(
        diff_config = {
            'exec_numMotes': 3,
            'conn_class'   : 'FullyMeshed'
        }
    )

    root  = sim_engine.motes[0]
    mote_1 = sim_engine.motes[1]
    mote_2 = sim_engine.motes[2]
    asn_at_end_of_simulation = (
        sim_engine.settings.tsch_slotframeLength *
        sim_engine.settings.exec_numSlotframesPerRun
    )

    u.run_until_everyone_joined(sim_engine)
    assert sim_engine.getAsn() < asn_at_end_of_simulation

    # We're making the RPL topology of "root -- mote_1 (-- mote_2)"
    dio_from_root = root.rpl._create_DIO()
    dio_from_root['mac'] = {'srcMac': root.get_mac_addr()}
    dio_from_root['app']['rank'] = 256
    mote_1.rpl.action_receiveDIO(dio_from_root)
    assert mote_1.rpl.getPreferredParent() == root.get_mac_addr()

    # Then, put mote_1 behind mote_2:    "root -- mote_2 -- mote_1"
    mote_2.rpl.action_receiveDIO(dio_from_root)
    dio_from_mote_2 = mote_2.rpl._create_DIO()
    dio_from_mote_2['mac'] = {'srcMac': mote_2.get_mac_addr()}

    dio_from_root['app']['rank'] = 65535
    mote_1.rpl.action_receiveDIO(dio_from_root)

    dio_from_mote_2['app']['rank'] = 256
    # inject DIO from mote_2 to mote_1
    mote_1.rpl.action_receiveDIO(dio_from_mote_2)

    assert mote_1.rpl.getPreferredParent() == mote_2.get_mac_addr()
    assert mote_2.rpl.getPreferredParent() == root.get_mac_addr()

    # create a dummy packet, which is used to get the next hop
    dummy_packet = {
        'net': {
            'srcIp': mote_1.get_ipv6_global_addr(),
            'dstIp': root.get_ipv6_global_addr()
        }
    }

    # the next hop should be parent
    assert mote_1.sixlowpan.find_nexthop_mac_addr(dummy_packet) == mote_1.rpl.getPreferredParent()


class TestOF0(object):
    def test_rank_computation(self, sim_engine):
        # https://tools.ietf.org/html/rfc8180#section-5.1.2
        sim_engine = sim_engine(
            diff_config = {
                'exec_numMotes'           : 6,
                'exec_numSlotframesPerRun': 10000,
                'app_pkPeriod'            : 0,
                'secjoin_enabled'         : False,
                'tsch_keep_alive_interval': 0,
                'conn_class'              : 'Linear',
            }
        )

        # shorthand
        motes = sim_engine.motes
        asn_at_end_of_simulation = (
            sim_engine.settings.tsch_slotframeLength *
            sim_engine.settings.exec_numSlotframesPerRun
        )

        # get the network ready to be test
        u.run_until_everyone_joined(sim_engine)
        assert sim_engine.getAsn() < asn_at_end_of_simulation

        # set ETX=100/75 (numTx=100, numTxAck=75)
        for mote_id in range(1, len(motes)):
            mote = motes[mote_id]
            parent = motes[mote_id - 1]

            # inject DIO to the mote
            dio = parent.rpl._create_DIO()
            dio['mac'] = {'srcMac': parent.get_mac_addr()}
            mote.rpl.action_receiveDIO(dio)

            # set numTx and numTxAck
            preferred_parent = mote.rpl.of.preferred_parent
            preferred_parent['numTx'] = 100
            preferred_parent['numTxAck'] = 75
            mote.rpl.of._update_neighbor_rank_increase(preferred_parent)

        # test using rank values in Figure 4 of RFC 8180
        assert motes[0].rpl.get_rank()   == 256
        assert motes[0].rpl.getDagRank() == 1

        print motes[1].rpl.of.preferred_parent
        assert motes[1].rpl.get_rank()   == 768
        assert motes[1].rpl.getDagRank() == 3

        assert motes[2].rpl.get_rank()   == 1280
        assert motes[2].rpl.getDagRank() == 5

        assert motes[3].rpl.get_rank()   == 1792
        assert motes[3].rpl.getDagRank() == 7

        assert motes[4].rpl.get_rank()   == 2304
        assert motes[4].rpl.getDagRank() == 9

        assert motes[5].rpl.get_rank()   == 2816
        assert motes[5].rpl.getDagRank() == 11

    def test_parent_switch(self, sim_engine):
        sim_engine = sim_engine(
            diff_config = {
                'exec_numMotes'  : 4,
                'secjoin_enabled': False
            }
        )

        # short-hand
        root = sim_engine.motes[0]
        mote_1 = sim_engine.motes[1]
        mote_2 = sim_engine.motes[2]
        mote_3 = sim_engine.motes[3]

        # let all the motes get synchronized
        eb = root.tsch._create_EB()
        mote_1.tsch._action_receiveEB(eb)
        mote_2.tsch._action_receiveEB(eb)
        mote_3.tsch._action_receiveEB(eb)

        # let mote_1 and mote_2 join the RPL network
        dio_from_root = root.rpl._create_DIO()
        dio_from_root['mac'] = {'srcMac': root.get_mac_addr()}
        mote_1.rpl.action_receiveDIO(dio_from_root)
        mote_2.rpl.action_receiveDIO(dio_from_root)

        dio_from_mote_1 = mote_1.rpl._create_DIO()
        dio_from_mote_1['mac'] = {'srcMac': mote_1.get_mac_addr()}
        dio_from_mote_2 = mote_2.rpl._create_DIO()
        dio_from_mote_2['mac'] = {'srcMac': mote_2.get_mac_addr()}

        # manipulate ranks in DIOs
        assert dio_from_root['app']['rank'] == 256
        dio_from_mote_1['app']['rank'] = 256 + 1
        dio_from_mote_2['app']['rank'] = (
            dio_from_mote_1['app']['rank'] +
            mote_3.rpl.of.PARENT_SWITCH_THRESHOLD
        )

        # inject DIO from mote_2 to mote_3
        mote_3.rpl.action_receiveDIO(dio_from_mote_2)
        assert mote_3.rpl.getPreferredParent() == mote_2.get_mac_addr()

        # inject DIO from mote_1 to mote_3; no parent switch
        mote_3.rpl.action_receiveDIO(dio_from_mote_1)
        assert mote_3.rpl.getPreferredParent() == mote_2.get_mac_addr()

        # inject DIO from root to mote_3; root becomes the new parent
        mote_3.rpl.action_receiveDIO(dio_from_root)
        assert mote_3.rpl.getPreferredParent() == root.get_mac_addr()

    def test_infinite_rank_reception(self, sim_engine):
        sim_engine = sim_engine(
            diff_config = {
                'exec_numMotes'  : 2,
                'secjoin_enabled': False
            }
        )

        root = sim_engine.motes[0]
        mote = sim_engine.motes[1]

        # get mote synched
        eb = root.tsch._create_EB()
        mote.tsch._action_receiveEB(eb)

        # inject the DIO to mote, which shouldn't cause any exception
        dio_with_infinite_rank = root.rpl._create_DIO()
        dio_with_infinite_rank['mac'] = {
            'srcMac': root.get_mac_addr(),
            'dstMac': d.BROADCAST_ADDRESS
        }
        dio_with_infinite_rank['app']['rank'] = rpl.RplOF0.INFINITE_RANK
        mote.rpl.action_receiveDIO(dio_with_infinite_rank)

        # mote should not treat the root (the source of the DIO) as a parent
        # since it advertises the infinite rank (see section 8.2.2.5, RFC
        # 6550). In other words, mote shouldn't have any effective rank. It
        # should have None for its rank.
        assert mote.rpl.of.get_rank() is None


@pytest.fixture(params=['dis_unicast', 'dis_broadcast', None])
def fixture_dis_mode(request):
    return request.param


def test_dis(sim_engine, fixture_dis_mode):
    sim_engine = sim_engine(
        diff_config = {
            'exec_numMotes' : 2,
            'rpl_extensions': [fixture_dis_mode]
        }
    )

    root = sim_engine.motes[0]
    mote = sim_engine.motes[1]

    # give EB to mote
    eb = root.tsch._create_EB()
    mote.tsch._action_receiveEB(eb)

    # prepare sendPacket() for this test
    sednPacket_is_called = False
    result = {'dis': None, 'dio': None}
    def sendPacket(self, packet):
        if packet['type'] == d.PKT_TYPE_DIS:
            dstIp = packet['net']['dstIp']
            if fixture_dis_mode == 'dis_unicast':
                assert dstIp == root.get_ipv6_link_local_addr()
            else:
                assert dstIp == d.IPV6_ALL_RPL_NODES_ADDRESS
            result['dis'] = packet
        elif packet['type'] == d.PKT_TYPE_DIO:
            dstIp = packet['net']['dstIp']
            if fixture_dis_mode == 'dis_unicast':
                assert dstIp == mote.get_ipv6_link_local_addr()
            else:
                assert dstIp == d.IPV6_ALL_RPL_NODES_ADDRESS
            result['dio'] = packet

    mote.sixlowpan.sendPacket = types.MethodType(sendPacket, mote.sixlowpan)
    root.sixlowpan.sendPacket = types.MethodType(sendPacket, root.sixlowpan)
    mote.rpl._send_DIS()

    if fixture_dis_mode is None:
        assert result['dis'] is None
        assert result['dio'] is None
    else:
        assert result['dis'] is not None
        root.rpl.action_receiveDIS(result['dis'])
    if fixture_dis_mode == 'dis_unicast':
        assert result['dio'] is not None
    else:
        # DIS is not sent immediately
        assert result['dio'] is None
