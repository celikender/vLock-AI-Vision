"""Clock-driven tests of the actual Gateway site library; no physical commands."""
import types
import unittest
from unittest.mock import Mock

from test_project import bridge, ready


class SiteTests(unittest.TestCase):
    def setup_site(self, state='Running'):
        ns, system, client, values=bridge()
        ready(ns,values)
        values.update({'Readings/State':state,'Readings/Online':True})
        original=ns['command']
        ns['command']=Mock(wraps=original)
        return ns,system,client,values,ns['_test_site']

    def test_active_latches_and_queues_exactly_one_pause(self):
        ns,system,client,v,site=self.setup_site()
        v['[default]vLock/A-101/State']='Active'
        site['tick'](); site['tick'](); site['tick']()
        self.assertTrue(v['System/StopLatched'])
        self.assertFalse(v['System/Enabled'])
        ns['command'].assert_called_once_with('Pause')
        self.assertTrue(v['Commands/Pause'])
        self.assertFalse(v['Commands/Stop'])
        self.assertFalse(v['Commands/Resume'])

    def test_unknown_and_each_bad_source_wait_two_seconds(self):
        faults=['Unknown','State','Quality','Reason','Online','HeartbeatCounter','quality_value','offline','Valid']
        for fault in faults:
            with self.subTest(fault=fault):
                ns,system,client,v,site=self.setup_site()
                if fault in ('Unknown','Valid'): v['[default]vLock/A-101/State']=fault
                elif fault=='quality_value': v['[default]vLock/A-101/Quality']='Stale'
                elif fault=='offline': v['[default]vLock/Bridge/Online']=False
                else:
                    root='[default]vLock/Bridge/' if fault in ('Online','HeartbeatCounter') else '[default]vLock/A-101/'
                    ns['_test_bad'].add(root+fault)
                start=ns['_test_now'][0]
                site['tick']()
                ns['_test_now'][0]=start+1.999; site['tick']()
                self.assertFalse(v['System/StopLatched'])
                ns['_test_now'][0]=start+2; site['tick'](); site['tick']()
                self.assertTrue(v['System/StopLatched'])
                ns['command'].assert_called_once_with('Pause')

    def test_short_unknown_recovers_and_restarts_debounce(self):
        ns,system,client,v,site=self.setup_site()
        v['[default]vLock/A-101/State']='Unknown'; site['tick']()
        ns['_test_now'][0]+=1
        v['[default]vLock/A-101/State']='Clear'; site['tick']()
        v['[default]vLock/A-101/State']='Unknown'; site['tick']()
        ns['_test_now'][0]+=1.1; site['tick']()
        self.assertFalse(v['System/StopLatched'])
        ns['command'].assert_not_called()

    def test_frozen_counter_latches_only_over_five_seconds(self):
        ns,system,client,v,site=self.setup_site()
        ns['_test_now'][0]+=5; site['tick']()
        self.assertFalse(v['System/StopLatched'])
        ns['_test_now'][0]+=0.001; site['tick'](); site['tick']()
        self.assertTrue(v['System/StopLatched'])
        ns['command'].assert_called_once_with('Pause')

    def test_first_counter_alone_is_not_a_moving_heartbeat(self):
        ns,system,client,v=bridge()
        ns['_test_site']['tick']()
        with self.assertRaises(ValueError): ns['system_command']('Reset')
        with self.assertRaises(ValueError): ns['system_command']('Start')
        self.assertFalse(v['System/CanReset'])

    def test_system_stop_uses_pause_and_invalidates_reset(self):
        ns,system,client,v,site=self.setup_site()
        ns['system_command']('Reset'); ns['system_command']('Start')
        ns['system_command']('Stop')
        self.assertTrue(v['System/StopLatched'])
        self.assertFalse(v['System/ResetValid'])
        self.assertFalse(v['System/Enabled'])
        ns['command'].assert_called_once_with('Pause')
        client.post.assert_not_called()

    def test_clear_reset_and_start_never_resume_and_both_reset_targets_match(self):
        for target in ('farm','P1S-01'):
            with self.subTest(target=target):
                ns,system,client,v,site=self.setup_site('Paused')
                v['[default]vLock/A-101/State']='Active'; site['tick']()
                v['[default]vLock/A-101/State']='Clear'; site['tick']()
                self.assertTrue(v['System/StopLatched'])
                ns['system_command']('Reset',target)
                self.assertFalse(v['System/StopLatched'])
                self.assertFalse(v['System/Enabled'])
                ns['system_command']('Start')
                self.assertTrue(v['System/Enabled'])
                self.assertFalse(v['Commands/Resume'])
                ns['command'].assert_not_called()
                client.get.assert_not_called(); client.post.assert_not_called()

    def test_reset_refused_when_active_bad_offline_or_frozen(self):
        for fault in ('active','bad','quality','offline','frozen'):
            with self.subTest(fault=fault):
                ns,system,client,v,site=self.setup_site('Paused')
                v['System/StopLatched']=True
                if fault=='active': v['[default]vLock/A-101/State']='Active'
                elif fault=='bad': ns['_test_bad'].add('[default]vLock/A-101/State')
                elif fault=='quality': v['[default]vLock/A-101/Quality']='Unknown'
                elif fault=='offline': v['[default]vLock/Bridge/Online']=False
                else: ns['_test_now'][0]+=5.001
                with self.assertRaises(ValueError): ns['system_command']('Reset')
                self.assertTrue(v['System/StopLatched'])
                ns['command'].assert_not_called(); client.post.assert_not_called()

    def test_resume_requires_click_valid_reset_and_start(self):
        ns,system,client,v,site=self.setup_site('Paused')
        with self.assertRaises(ValueError): ns['command']('Resume')
        ns['system_command']('Reset')
        with self.assertRaises(ValueError): ns['command']('Resume')
        ns['system_command']('Start')
        client.get.return_value=types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Paused'})
        client.post.return_value=types.SimpleNamespace(good=True,json={'result':'Resume accepted'})
        system.util.invokeAsynchronous.side_effect=lambda fn: fn()
        ns['_dispatch']('Resume')  # A bare tag/direct dispatch is not an operator intent.
        client.post.assert_not_called()
        ns['command']('Resume'); ns['_dispatch']('Resume')
        self.assertEqual(client.post.call_args.kwargs['data']['action'],'Resume')

    def test_latch_invalidates_a_resume_already_queued(self):
        ns,system,client,v,site=self.setup_site('Paused')
        ns['system_command']('Reset'); ns['system_command']('Start')
        ns['command']('Resume')
        jobs=[]
        system.util.invokeAsynchronous.side_effect=jobs.append
        ns['_dispatch']('Resume')
        v['[default]vLock/A-101/State']='Active'; site['tick']()
        v['[default]vLock/A-101/State']='Clear'
        ns['system_command']('Reset'); ns['system_command']('Start')
        client.get.return_value=types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Paused'})
        jobs[0]()
        client.post.assert_not_called()
        self.assertIn('expired',v['Commands/Result'])

    def test_pending_latch_waits_for_first_running_report_without_retries(self):
        ns,system,client,v,site=self.setup_site('Idle')
        v['[default]vLock/A-101/State']='Active'; site['tick']()
        ns['command'].assert_not_called()
        v['Readings/State']='Running'; site['tick'](); site['tick']()
        ns['command'].assert_called_once_with('Pause')

    def test_transient_unknown_cannot_release_an_old_resume_when_clear_returns(self):
        ns,system,client,v,site=self.setup_site('Paused')
        ns['system_command']('Reset'); ns['system_command']('Start')
        ns['command']('Resume')
        jobs=[]
        system.util.invokeAsynchronous.side_effect=jobs.append
        ns['_dispatch']('Resume')
        v['[default]vLock/A-101/State']='Unknown'; site['tick']()
        ns['_test_now'][0]+=1
        v['[default]vLock/A-101/State']='Clear'; site['tick']()
        self.assertFalse(v['System/StopLatched'])
        client.get.return_value=types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Paused'})
        jobs[0]()
        client.post.assert_not_called()

    def test_pause_is_not_dropped_while_a_resume_worker_is_busy(self):
        ns,system,client,v,site=self.setup_site()
        ns['_busy'].set(True)
        client.get.return_value=types.SimpleNamespace(good=True,json={'online':True,'mqtt_connected':True,'state':'Running'})
        client.post.return_value=types.SimpleNamespace(good=True,json={'result':'Pause accepted'})
        system.util.invokeAsynchronous.side_effect=lambda fn: fn()
        ns['_dispatch']('Pause')
        self.assertEqual(client.post.call_args.kwargs['data']['action'],'Pause')

    def test_reload_preserves_latch_but_requires_new_reset_and_start(self):
        ns,system,client,v,site=self.setup_site('Paused')
        ns['system_command']('Reset'); ns['system_command']('Start')
        v['System/StopLatched']=True
        site['_ready']=False
        site['initialize']()
        self.assertTrue(v['System/StopLatched'])
        self.assertFalse(v['System/Enabled'])
        self.assertFalse(v['System/ResetValid'])


if __name__=='__main__': unittest.main()
