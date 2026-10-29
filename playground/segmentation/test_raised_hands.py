import unittest
import time
from raised_hands import RaisedHands
from monitor import Monitor


def detection(x,y,width=.06,height=.06):
    return {'center':[x,y],'bbox':[x-width/2,y-height/2,x+width/2,y+height/2],'area':width*height}


def scene(y=.2,offset=0):
    return {'hand':[detection(.2,y),detection(.8,y)],
            'head':[detection(.5,.5+offset,.2,.2)],
            'person':[detection(.5,.5,1,1)]}


class RaisedHandsTests(unittest.TestCase):
    def test_same_frame_concepts_trigger_local_event(self):
        frames=[]
        def fetch(address):
            frame=str(len(frames)+1).encode()
            frames.append(frame)
            return frame, {'X-Frame-Sequence':str(len(frames)),'X-Frame-Age-Ms':'0'}
        calls=[]
        def infer(jpeg, concept, backend):
            calls.append((jpeg,concept,backend))
            sample=scene(.3-min(int(jpeg),4)*.05)
            return {'count':len(sample[concept]),'detections':sample[concept],
                    'elapsed_seconds':.1,'peak_vram_mb':100}
        monitor=Monitor(fetch=fetch,infer=infer)
        monitor.start('192.168.1.50','unused','hands_above_head_moving')
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                events=monitor.status()['events']
                if any(e['type']=='both_hands_raised_moving' for e in events):
                    break
                time.sleep(.05)
            self.assertTrue(any(e['type']=='both_hands_raised_moving' for e in events))
            for frame in frames[:3]:
                self.assertEqual([(c,b) for f,c,b in calls if f==frame],
                                 [('hand','local'),('head','local'),('person','local')])
        finally:
            monitor.stop()
            monitor.thread.join(2)

    def test_raised_motion_and_order(self):
        rule=RaisedHands()
        self.assertIsNone(rule.evaluate(scene())[0])
        next_scene=scene(.14)
        next_scene['hand'].reverse()
        self.assertEqual(rule.evaluate(next_scene)[0],1)
        self.assertEqual(rule.evaluate(next_scene)[0],0)

    def test_moving_below_head_is_inactive(self):
        rule=RaisedHands()
        self.assertEqual(rule.evaluate(scene(.7))[0],0)
        self.assertEqual(rule.evaluate(scene(.6))[0],0)

    def test_one_hand_moving_not_enough(self):
        rule=RaisedHands()
        rule.evaluate(scene())
        sample=scene()
        sample['hand'][0]=detection(.2,.14)
        self.assertEqual(rule.evaluate(sample)[0],0)

    def test_missing_and_multiple_people_reset(self):
        rule=RaisedHands()
        rule.evaluate(scene())
        sample=scene(.14)
        sample['person'] *= 2
        self.assertIsNone(rule.evaluate(sample)[0])
        self.assertIsNone(rule.evaluate(scene(.08))[0])
        sample=scene()
        sample['head']=[]
        self.assertIsNone(rule.evaluate(sample)[0])

    def test_translation_relative_to_head_not_motion(self):
        rule=RaisedHands()
        rule.evaluate(scene())
        self.assertEqual(rule.evaluate(scene(.26,.06))[0],0)

    def test_hand_outside_person_unknown(self):
        sample=scene()
        sample['person']=[detection(.5,.5,.3,.9)]
        self.assertIsNone(RaisedHands().evaluate(sample)[0])

    def test_old_cloud_rule_rejected(self):
        with self.assertRaises(ValueError):
            Monitor().start('192.168.1.50','person','stand_up')
