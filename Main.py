import os
import sys

# Point to your Python installation's tcl/tk libraries
python_root = sys.base_prefix  # Gets the base Python installation path
os.environ['TCL_LIBRARY'] = os.path.join(python_root, 'tcl', 'tcl8.6')
os.environ['TK_LIBRARY'] = os.path.join(python_root, 'tcl', 'tk8.6')
import salabim as sim
import random

direct_to_EMD = ['purple','red', 'orange','yellow']
teal_calls = ['teal']

# % of calls that an STC closes
stc_closure_rate = 0.2

# set number of resources
stc_count = 2
calltaker_count = 10
ambulance_count = 50
reassessor_count = 2

#Misc variables
teal_max_wait = 30 #longest time teal call will wait in tealQ
rea_timeframe = 30
rural_remote_stc = True
env = sim.Environment(trace=True)

#monitors for available resources:
active_stc_monitor = sim.Monitor(name='Active STC', level=True, initial_tally=0)
active_ambulance_monitor = sim.Monitor(name='Active Ambulances', level=True, initial_tally=0)
active_reassessor_monitor = sim.Monitor(name='Active REA EMCT', level=True, initial_tally=0)
active_emct_monitor = sim.Monitor(name='Active EMCT', level=True, initial_tally=0)

#Create the queues
emct_Q = sim.Queue('emct_Q')
teal_Q = sim.Queue('teal_Q')
purple_Q = sim.Queue('purple_Q')
red_Q = sim.Queue('red_Q')
orange_Q = sim.Queue('orange_Q')
yellow_Q = sim.Queue('yellow_Q')
rea_Q = sim.Queue('rea_Q')

# these need to be in priority order
event_colours = ['purple','red', 'orange','yellow','teal']
colour_priority = [colour+'_Q' for colour in event_colours]
colour_queues = {
    'purple': purple_Q,
    'red': red_Q,
    'orange': orange_Q,
    'yellow': yellow_Q
}

class CallGenerator(sim.Component):
    def process(self):
        while True:
            MPDS_Call()
            self.hold(sim.Uniform(0.8, 2).sample())

class MPDS_Call(sim.Component):
    def setup(self):
        self.rural_remote = random.choices(population=[True, False], weights=[0.3, 0.7], k=1)[0]
        self.processed_by_stc = False
        self.colour = None

    def process(self):
        # Get processed by an EMCT
        self.enter(emct_Q)
        self._activate_first_passive(Calltakers)
        self.passivate()
        # wait to be reactivated by a calltaker wrapping up with you
        self._determine_colour()
        if self.colour in teal_calls:
            self._handle_teal_call()
        elif self.colour in direct_to_EMD:
            self._handle_dispatchable_call()

        self.passivate()

    def _activate_first_passive(self, components):
        for component in components:
            if component.ispassive():
                component.activate()
                break

    def _determine_colour(self):
        gets_screened_in = (
                rural_remote_stc == True
                and self.rural_remote == True
                and self.colour == 'yellow'
        )
        if gets_screened_in:
            self.colour = 'teal'
        else:
            self.colour = random.choices(
                population=event_colours,
                weights=[3, 35, 28, 32, 2],
                k=1
            )[0]

    def _handle_dispatchable_call(self):
        self.enter(colour_queues[self.colour])
        self.reassessment_timer = ReassessmentTimer(call=self)
        self._activate_first_passive(Ambulances)

    def _handle_teal_call(self):
        self.enter(teal_Q)
        self._activate_first_passive(STCs)
        self.hold(teal_max_wait)

        if self in teal_Q:
            self._handle_teal_timeout()
        elif self.processed_by_stc:
            self._handle_stc_processed_call()

    def _handle_teal_timeout(self):
        # Move calls from teal to yellow after waiting too long to be assessed
        self.leave(teal_Q)
        env.teal_bounces += 1
        self._send_to_yellow_queue()

    def _handle_stc_processed_call(self):
        # either close the call or cancel depending on STC closure rate
        if random.random() < stc_closure_rate:
            env.stc_closed_count += 1
            self.cancel()
        else:
            self._send_to_yellow_queue()

    def _send_to_yellow_queue(self):
        """Send the call to the yellow queue for dispatch."""
        self.colour = 'yellow'
        self.enter(yellow_Q)


class STC(sim.Component):
    def process(self):
        while True:
            while len(teal_Q) == 0:
                self.passivate()
            active_stc_monitor.tally(active_stc_monitor.value + 1)
            self.MPDS_Call = teal_Q.pop()
            self.hold(25)
            self.MPDS_Call.processed_by_stc = True
            self.MPDS_Call.activate()
            active_stc_monitor.tally(active_stc_monitor.value - 1)


class ambulance(sim.Component):
    def process(self):
        while True:
            # Find a call from any queue (check ALL queues first)
            call_found = False
            for queue in colour_queues.values():
                if len(queue) > 0:
                    active_ambulance_monitor.tally(active_ambulance_monitor.value + 1)
                    self.MPDS_Call = queue.pop()
                    
                    # Stop the reassessment timer and remove from rea_Q
                    if hasattr(self.MPDS_Call, 'reassessment_timer') and self.MPDS_Call.reassessment_timer:
                        self.MPDS_Call.reassessment_timer.active = False
                    if self.MPDS_Call in rea_Q:
                        rea_Q.remove(self.MPDS_Call)
                    
                    if self.MPDS_Call.colour in ['purple', 'red']:
                        self.hold(90)
                    elif self.MPDS_Call.colour in ['orange', 'yellow']:
                        self.hold(random.choice([30, 45, 90, 120]))
                    self.MPDS_Call.cancel()
                    active_ambulance_monitor.tally(active_ambulance_monitor.value - 1)
                    call_found = True
                    break  # Handle one call, then loop back to check queues again

            # Only passivate if NO queues have any calls
            if not call_found:
                self.passivate()

class calltaker(sim.Component):
    def process(self):
        while True:
            while len(emct_Q) == 0:
                self.passivate()
            self.current_call = emct_Q.pop()
            active_emct_monitor.tally(active_emct_monitor.value + 1)
            self.hold(sim.Uniform(1, 10).sample())
            self.current_call.colour = random.choices(population=event_colours, weights=[3, 35, 28, 32, 2], k=1)[0]
            self.current_call.activate()
            active_emct_monitor.tally(active_emct_monitor.value - 1)


class ReassessmentTimer(sim.Component):
    def setup(self, call):
        self.call = call
        self.active = True
    def process(self):
        while self.active:
            self.hold(rea_timeframe)

            if self.active and self.call in colour_queues.get(self.call.colour, []):
                if self.call not in rea_Q:
                    self.call.enter(rea_Q)
                    for reassessor in Reassessors:
                        if reassessor.ispassive():
                            reassessor.activate()
                            break
            elif not self.active:
                break


class ReassessmentEMCT(sim.Component):
    def process(self):
        while True:
            while len(rea_Q) == 0:
                self.passivate()
            patient = rea_Q.pop()
            active_reassessor_monitor.tally(active_reassessor_monitor.value + 1)
            self.hold(sim.Triangular(2,5,4).sample())
            still_waiting = patient in colour_queues.get(patient.colour, [])
            if sim.Uniform(0, 1).sample() < 0.05:
                patient.reassessment_timer.active = False
                patient.cancel()
            elif still_waiting:
                # this whole try/except block is dumb - I get an error when I tried to just do enter that some calls were already in there despite being popped minutes ago.
                try:
                    patient.leave(rea_Q)
                except ValueError:
                    pass
                finally:
                    patient.enter(rea_Q)
            active_reassessor_monitor.tally(active_reassessor_monitor.value - 1)

env.processed_count = 0
env.teal_bounces = 0
env.stc_closed_count = 0
env.animate(True)

CallGenerator()

STCs = [STC() for _ in range(stc_count)]
Ambulances = [ambulance() for _ in range(ambulance_count)]
Calltakers = [calltaker() for _ in range(calltaker_count)]
Reassessors = [ReassessmentEMCT() for _ in range(reassessor_count)]


#Teal Q visual
sim.AnimateText(
    text=lambda: f"Teal Queue: {len(teal_Q)}",
    x=50,
    y=150,
    fontsize=20,
    textcolor='teal'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(teal_Q) * 10, 20),
    x=250,
    y=145,
    fillcolor='teal'
)

#Yellow Q visual
sim.AnimateText(
    text=lambda: f"Yellow Queue: {len(yellow_Q)}",
    x=50,
    y=120,
    fontsize=20,
    textcolor='yellow'
)

sim.AnimateRectangle(
    spec=lambda: (0, 0, len(yellow_Q) * 10, 20),
    x=250,
    y=115,
    fillcolor='yellow'
)
#Orange Q visual
sim.AnimateText(
    text=lambda: f"Orange Queue: {len(orange_Q)}",
    x=50,
    y=90,
    fontsize=20,
    textcolor='orange'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(orange_Q) * 10, 20),
    x=250,
    y=85,
    fillcolor='orange'
)

#Red Q visual
sim.AnimateText(
    text=lambda: f"Red Queue: {len(red_Q)}",
    x=50,
    y=60,
    fontsize=20,
    textcolor='red'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(red_Q) * 10, 20),
    x=250,
    y=55,
    fillcolor='red'
)
#Purple Q visual
sim.AnimateText(
    text=lambda: f"Purple Queue: {len(purple_Q)}",
    x=50,
    y=30,
    fontsize=20,
    textcolor='purple'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(purple_Q) * 10, 20),
    x=250,
    y=25,
    fillcolor='purple'
)

#Active Colour visual
sim.AnimateMonitor(purple_Q.length_of_stay, x=10, y=520, width=700, height=150, horizontal_scale=5, vertical_scale=20, linecolor='purple', title = '')
sim.AnimateMonitor(red_Q.length_of_stay, x=10, y=520, width=700, height=150, horizontal_scale=5, vertical_scale=20, linecolor='red', title = '')
sim.AnimateMonitor(orange_Q.length_of_stay, x=10, y=520, width=700, height=150, horizontal_scale=5, vertical_scale=20, linecolor='orange', title = '')
sim.AnimateMonitor(yellow_Q.length_of_stay, x=10, y=520, width=700, height=150, horizontal_scale=5, vertical_scale=20, linecolor='yellow', fillcolor='#D3D3D3', title = 'length of stay in queue')

#Active STC Visual
sim.AnimateText(
    text=lambda: f"Active STC: {active_stc_monitor.value}",
    x=50,
    y=490,
    fontsize=20,
    textcolor='teal'
)
sim.AnimateText(
    text=lambda: f"Available STC: {stc_count-(active_stc_monitor.value)}",
    x=50,
    y=460,
    fontsize=20,
    textcolor='teal'
)
# Bounced teals visual
sim.AnimateText(
    text=lambda: f"Bounced Teals: {env.teal_bounces}",
    x=50,
    y=430,
    fontsize=20,
    textcolor='teal'
)
# STC Closed visual
sim.AnimateText(
    text=lambda: f"STC Closed Calls: {env.stc_closed_count}",
    x=50,
    y=390,
    fontsize=20,
    textcolor='teal'
)

#Active Ambulances visual
sim.AnimateText(
    text=lambda: f"Active Ambulances: {active_ambulance_monitor.value}",
    x=300,
    y=490,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Available Ambulances: {ambulance_count-(active_ambulance_monitor.value)}",
    x=300,
    y=460,
    fontsize=20,
    textcolor='black'
)

#Active Rea visual
sim.AnimateText(
    text=lambda: f"Active REA: {active_reassessor_monitor.value}",
    x=300,
    y=420,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Available REA: {reassessor_count-(active_reassessor_monitor.value)}",
    x=300,
    y=390,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"REA Waiting: {rea_Q.length()}",
    x=300,
    y=360,
    fontsize=20,
    textcolor='black'
)
# EMCT Data
sim.AnimateText(
    text=lambda: f"911 Waiting: {emct_Q.length()}",
    x=300,
    y=300,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Active EMCT: {active_emct_monitor.value}",
    x=300,
    y=270,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Available EMCT: {(calltaker_count-(active_emct_monitor.value))}",
    x=300,
    y=240,
    fontsize=20,
    textcolor='black'
)

# Speed display
sim.AnimateText(
    text=lambda: f"Speed: {env.speed()}x",
    x=310,
    y=690,
    fontsize=16,
    textcolor='black'
)

# Speed control buttons
def set_speed_1():
    env.speed(1)
def set_speed_10():
    env.speed(10)
def set_speed_100():
    env.speed(100)
def set_speed_40():
    env.speed(40)

sim.AnimateButton(text="1x", x=50, y=700, action=set_speed_1)
sim.AnimateButton(text="10x", x=120, y=700, action=set_speed_10)
sim.AnimateButton(text="40x", x=190, y=700, action=set_speed_40)
sim.AnimateButton(text="100x", x=260, y=700, action=set_speed_100)


try:
    env.run(till=10000)
except sim.SimulationStopped:
    print("\nSimulation was stopped by user (animation window closed).")
    print(f"Simulation ended at time: {env.now()}")


