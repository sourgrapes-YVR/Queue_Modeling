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
ambulance_count = 40
reassessor_count = 1

#Misc variables
teal_max_wait = 30 #longest time teal call will wait in tealQ
rea_timeframe = 30

env = sim.Environment(trace=True)

#monitors for available resources:
active_stc_monitor = sim.Monitor(name='Active STC', level=True, initial_tally=0)
active_ambulance_monitor = sim.Monitor(name='Active Ambulances', level=True, initial_tally=0)
active_reassessor_monitor = sim.Monitor(name='Active REA EMCT', level=True, initial_tally=0)

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
            self.hold(sim.Uniform(1, 2).sample())

class MPDS_Call(sim.Component):
    def setup(self):
        self.processed_by_stc = False
        self.colour = None
    def process(self):
        # Get processed by an EMCT
        self.enter(emct_Q)
        for calltaker in Calltakers:
            if calltaker.ispassive():
                calltaker.activate()
                break
        self.passivate()
        # if it's dispatchable, send it out
        if self.colour in direct_to_EMD:
            self.enter(colour_queues[self.colour])
            # Create a reassessment timer for this call
            self.reassessment_timer = ReassessmentTimer(call=self)
            for ambulance in Ambulances:
                if ambulance.ispassive():
                    ambulance.activate()
                    break
        # if it's teal, send to teal Q
        elif self.colour in teal_calls:
            self.enter(teal_Q)
            # if STC available, send to them
            for stc in STCs:
                if stc.ispassive():
                    stc.activate()
                    break
            # if no STC, wait up to 30 mins then if still in teal Q send to pending
            self.hold(teal_max_wait)
            if self in teal_Q:
                self.leave(teal_Q)
                env.teal_bounces += 1
                self.colour = 'yellow'
                self.enter(yellow_Q)
            elif self.processed_by_stc:
                # STC handled this call - check if cancelled or goes to pending
                if random.random() < stc_closure_rate:
                    env.stc_closed_count += 1  # Successfully cancelled
                    self.cancel()
                else:
                    self.colour = 'yellow'
                    self.enter(yellow_Q)  # Still needs dispatch
        self.passivate()

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
            self.hold(sim.Uniform(1, 10).sample())
            self.current_call.colour = random.choices(population=event_colours, weights=[10, 20, 30, 30, 10], k=1)[0]
            self.current_call.activate()

class ReassessmentTimer(sim.Component):
    def setup(self,call):
        self.call = call
    def process(self):
        while True:
            self.hold(rea_timeframe)
            if self.call in colour_queues[self.call.colour]:
                self.call.enter(rea_Q)
                for reassessor in Reassessors:
                    if reassessor.ispassive():
                        reassessor.activate()
                        break
                self.passivate()
                self.passivate()
            else:
                break

class ReassessmentEMCT(sim.Component):
    def process(self):
        while True:
            while len(rea_Q) == 0:
                self.passivate()
            patient = rea_Q.pop()
            active_reassessor_monitor.tally(active_reassessor_monitor.value + 1)
            self.hold(sim.Triangular(2,5,4).sample())
            if sim.Uniform(0,1).sample() < 0.05:
                patient.cancel()
            else:
                if patient.reassessment_timer is not None:
                    patient.reassessment_timer.activate()
                patient.activate()
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
    y=120,
    fontsize=20,
    textcolor='teal'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(teal_Q) * 10, 20),
    x=250,
    y=115,
    fillcolor='teal'
)

#Yellow Q visual
sim.AnimateText(
    text=lambda: f"Yellow Queue: {len(yellow_Q)}",
    x=50,
    y=90,
    fontsize=20,
    textcolor='yellow'
)

sim.AnimateRectangle(
    spec=lambda: (0, 0, len(yellow_Q) * 10, 20),
    x=250,
    y=85,
    fillcolor='yellow'
)
#Orange Q visual
sim.AnimateText(
    text=lambda: f"Orange Queue: {len(orange_Q)}",
    x=50,
    y=60,
    fontsize=20,
    textcolor='orange'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(orange_Q) * 10, 20),
    x=250,
    y=55,
    fillcolor='orange'
)

#Red Q visual
sim.AnimateText(
    text=lambda: f"Red Queue: {len(red_Q)}",
    x=50,
    y=30,
    fontsize=20,
    textcolor='red'
)
sim.AnimateRectangle(
    spec=lambda: (0, 0, len(red_Q) * 10, 20),
    x=250,
    y=25,
    fillcolor='red'
)

#Active STC visual
sim.AnimateMonitor(active_stc_monitor, x=10, y=570, width=480, height=100, horizontal_scale=5, vertical_scale=5)

sim.AnimateText(
    text=lambda: f"Active STC: {active_stc_monitor.value}",
    x=50,
    y=550,
    fontsize=20,
    textcolor='teal'
)
sim.AnimateText(
    text=lambda: f"Available STC: {stc_count-(active_stc_monitor.value)}",
    x=50,
    y=520,
    fontsize=20,
    textcolor='teal'
)

#Active Ambulances visual

sim.AnimateText(
    text=lambda: f"Active Ambulances: {active_ambulance_monitor.value}",
    x=300,
    y=550,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Available Ambulances: {ambulance_count-(active_ambulance_monitor.value)}",
    x=300,
    y=520,
    fontsize=20,
    textcolor='black'
)

#Active Rea visual
sim.AnimateText(
    text=lambda: f"Active REA: {active_reassessor_monitor.value}",
    x=300,
    y=450,
    fontsize=20,
    textcolor='black'
)
sim.AnimateText(
    text=lambda: f"Available REA: {reassessor_count-(active_reassessor_monitor.value)}",
    x=300,
    y=420,
    fontsize=20,
    textcolor='black'
)

sim.AnimateText(
    text=lambda: f"REA Waiting: {rea_Q.length()}",
    x=600,
    y=480,
    fontsize=20,
    textcolor='black'
)

# Bounced teals visual
sim.AnimateText(
    text=lambda: f"Bounced Teals: {env.teal_bounces}",
    x=600,
    y=60,
    fontsize=20,
    textcolor='green'
)

sim.AnimateRectangle(
    spec=lambda: (0, 0, env.processed_count * 2, 20),
    x=250,
    y=55,
    fillcolor='green'
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
def set_speed_1000():
    env.speed(1000)

sim.AnimateButton(text="1x", x=50, y=700, action=set_speed_1)
sim.AnimateButton(text="10x", x=120, y=700, action=set_speed_10)
sim.AnimateButton(text="100x", x=190, y=700, action=set_speed_100)
sim.AnimateButton(text="1000x", x=260, y=700, action=set_speed_1000)


try:
    env.run(till=1000)
except sim.SimulationStopped:
    print("\nSimulation was stopped by user (animation window closed).")
    print(f"Simulation ended at time: {env.now()}")


