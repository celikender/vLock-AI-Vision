"""Explicit placeholder until observation-output service wiring is enabled."""


class UnwiredOutput:
    def __init__(self):
        self.status = dict(state='disabled',message='Observation output not connected.',last_sent_at=None)

    def send(self,*args,**kwargs):
        pass
