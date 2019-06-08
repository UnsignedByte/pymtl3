"""
========================================================================
ComponentLevel5_test.py
========================================================================

Author : Shunning Jiang
Date   : Jan 4, 2019
"""
from __future__ import absolute_import, division, print_function

from collections import deque

from pymtl3.datatypes import Bits1, Bits32
from pymtl3.dsl.ComponentLevel5 import ComponentLevel5, method_port
from pymtl3.dsl.Connectable import CalleePort, CallerPort, InPort, Interface, OutPort
from pymtl3.dsl.ConstraintTypes import M, U

from .sim_utils import simple_sim_pass


def _test_model( cls ):
  A = cls()
  A.elaborate()
  simple_sim_pass( A, 0x123 )

  print()
  T, time = 0, 20
  while not A.done() and T < time:
    A.tick()
    print(A.line_trace())
    T += 1
  return T

class SimpleTestSource( ComponentLevel5 ):

  def construct( s, msgs ):
    s.msgs = deque( msgs )

    s.req     = CallerPort()
    s.req_rdy = CallerPort()

    s.v = 0
    @s.update
    def up_src():
      s.v = None
      if s.req_rdy() and s.msgs:
        s.v = s.msgs.popleft()
        s.req( s.v )

  def done( s ):
    return not s.msgs

  def line_trace( s ):
    return "{:4}".format( "" if s.v is None else s.v )

class TestSinkError( Exception ):
  pass

class SimpleTestSink( ComponentLevel5 ):

  def resp_( s, msg ):
    ref = s.msgs[ s.idx ]
    s.idx += 1

    if msg != ref:
      raise TestSinkError( """
The test sink received an incorrect message!
- sink name    : {}
- msg number   : {}
- expected msg : {}
- actual msg   : {}
""".format( s, s.idx, ref, msg )
      )

  def resp_rdy_( s ):
    return True

  def construct( s, msgs ):
    s.msgs = list( msgs )
    s.idx  = 0

    s.resp     = CalleePort( method = s.resp_     )
    s.resp_rdy = CalleePort( method = s.resp_rdy_ )

  def done( s ):
    return s.idx >= len(s.msgs)

  def line_trace( s ):
    return ""

def test_simple_src_dumb_sink():

  class Top( ComponentLevel5 ):

    def construct( s ):
      s.src  = SimpleTestSource( [1,2,3,4] )
      s.sink = SimpleTestSink( [1,2,3,4] )

      s.connect_pairs(
        s.src.req,     s.sink.resp,
        s.src.req_rdy, s.sink.resp_rdy,
      )

    def done( s ):
      return s.src.done() and s.sink.done()

    def line_trace( s ):
      return  s.src.line_trace() + " >>> " + s.sink.line_trace()


  assert _test_model( Top ) == 4 # regression: 4 cycles

class TestSinkUp( ComponentLevel5 ):

  def resp_rdy_( s ):
    return s.idx < len(s.msgs)

  def resp_( s, v ):
    s.queue.appendleft(v)

  def construct( s, msgs ):
    s.msgs  = list( msgs )
    s.queue = deque( maxlen=1 )
    s.idx  = 0

    s.resp     = CalleePort( method = s.resp_ )
    s.resp_rdy = CalleePort( method = s.resp_rdy_ )

    s.v = None

    @s.update
    def up_sink():
      s.v = None

      if s.queue:
        msg = s.queue.pop()
        s.v = msg

        if s.idx >= len(s.msgs):
          raise TestSinkError( """
  The test sink received a message that !
  - sink name    : {}
  - msg number   : {}
  - actual msg   : {}
  """.format( s, s.idx, msg )
          )
        else:
          ref = s.msgs[ s.idx ]
          s.idx += 1

          if msg != ref:
            raise TestSinkError( """
  The test sink received an incorrect message!
  - sink name    : {}
  - msg number   : {}
  - expected msg : {}
  - actual msg   : {}
  """.format( s, s.idx, ref, msg )
          )

    s.add_constraints(
      U(up_sink) < M(s.resp_    ), # pipe behavior
      U(up_sink) < M(s.resp_rdy_),
    )

  def done( s ):
    return s.idx >= len(s.msgs)

  def line_trace( s ):
    return "{:4}".format( "" if s.v is None else s.v )

def test_simple_src_up_sink():

  class Top( ComponentLevel5 ):

    def construct( s ):
      s.src  = SimpleTestSource( [1,2,3,4] )
      s.sink = TestSinkUp( [1,2,3,4] )

      s.connect_pairs(
        s.src.req,     s.sink.resp,
        s.src.req_rdy, s.sink.resp_rdy,
      )

    def done( s ):
      return s.src.done() and s.sink.done()

    def line_trace( s ):
      return  s.src.line_trace() + " >>> " + s.sink.line_trace()

  assert _test_model( Top ) == 5 # regression: 5 cycles

class PassThrough( ComponentLevel5 ):

  @method_port
  def req( s, msg ):
    assert s.resp_rdy()
    s.resp( msg )

  @method_port
  def req_rdy( s ):
    return s.resp_rdy()

  def construct( s ):
    s.resp     = CalleePort()
    s.resp_rdy = CalleePort()
    s.entry = None

    s.add_constraints(
      M(s.req) == M(s.resp),
      M(s.req_rdy) == M(s.resp_rdy),
    )

def test_constraint_equal_pass_through():

  class Top( ComponentLevel5 ):

    def construct( s ):
      s.src  = SimpleTestSource( [1,2,3,4] )
      s.mid  = PassThrough()
      s.sink = TestSinkUp( [1,2,3,4] )

      s.connect_pairs(
        s.src.req,     s.mid.req,
        s.src.req_rdy, s.mid.req_rdy,
        s.mid.resp,    s.sink.resp,
        s.mid.resp_rdy, s.sink.resp_rdy,
      )

    def done( s ):
      return s.src.done() and s.sink.done()

    def line_trace( s ):
      return  s.src.line_trace() + " >>> " + s.sink.line_trace()

  assert _test_model( Top ) == 5 # regression: 5 cycles

def test_constraint_equal_pass_way_through():

  class Top( ComponentLevel5 ):

    def construct( s ):
      s.src  = SimpleTestSource( [1,2,3,4] )
      s.mid  = [ PassThrough() for _ in range(5) ]
      s.sink = TestSinkUp( [1,2,3,4] )

      s.connect_pairs(
        s.src.req,     s.mid[0].req,
        s.src.req_rdy, s.mid[0].req_rdy,
      )

      for i in range(4):
        s.connect_pairs(
          s.mid[i].resp, s.mid[i+1].req,
          s.mid[i].resp_rdy, s.mid[i+1].resp_rdy,
        )

      s.connect_pairs(
        s.mid[4].resp,    s.sink.resp,
        s.mid[4].resp_rdy, s.sink.resp_rdy,
      )

    def done( s ):
      return s.src.done() and s.sink.done()

    def line_trace( s ):
      return  s.src.line_trace() + " >>> " + s.sink.line_trace()

  assert _test_model( Top ) == 5 # regression: 5 cycles

def test_method_interface():

  class RecvIfcCL( Interface ):
    def construct( s, recv=None, rdy=None):
      s.recv = CalleePort( method = recv )
      s.rdy  = CalleePort( method = rdy )

    # Here we customize method interface connections
    def connect( s, other, parent ):
      if isinstance( other, SendIfcCL ):
        parent.connect_pairs(
          s.recv, other.send,
          s.rdy, other.rdy,
        )
        return True

      return False

  class SendIfcCL( Interface ):
    def construct( s ):
      s.send = CallerPort()
      s.rdy  = CallerPort()

    def connect( s, other, parent ):
      if isinstance( other, RecvIfcCL ):
        parent.connect_pairs(
          s.send, other.recv,
          s.rdy, other.rdy,
        )
        return True

      return False

  class SimpleTestSourceIfc( ComponentLevel5 ):

    def construct( s, msgs ):
      s.msgs = deque( msgs )

      s.req = SendIfcCL()

      s.v = 0
      @s.update
      def up_src():
        s.v = None
        if s.req.rdy() and s.msgs:
          s.v = s.msgs.popleft()
          s.req.send( s.v )

    def done( s ):
      return not s.msgs

    def line_trace( s ):
      return "{:4}".format( "" if s.v is None else s.v )

  class SimpleTestSinkIfc( ComponentLevel5 ):

    def resp_( s, msg ):
      ref = s.msgs[ s.idx ]
      s.idx += 1

      if msg != ref:
        raise TestSinkError( """
  The test sink received an incorrect message!
  - sink name    : {}
  - msg number   : {}
  - expected msg : {}
  - actual msg   : {}
  """.format( s, s.idx, ref, msg )
        )

    def resp_rdy_( s ):
      return True

    def construct( s, msgs ):
      s.msgs = list( msgs )
      s.idx  = 0

      s.resp = RecvIfcCL( recv = s.resp_, rdy = s.resp_rdy_ )

    def done( s ):
      return s.idx >= len(s.msgs)

    def line_trace( s ):
      return ""

  class Top( ComponentLevel5 ):

    def construct( s ):
      s.src  = SimpleTestSourceIfc( [1,2,3,4] )
      s.sink = SimpleTestSinkIfc( [1,2,3,4] )

      s.connect_pairs(
        s.src.req,     s.sink.resp,
      )

    def done( s ):
      return s.src.done() and s.sink.done()

    def line_trace( s ):
      return  s.src.line_trace() + " >>> " + s.sink.line_trace()

  assert _test_model( Top ) == 4 # regression: 4 cycles


def test_mix_cl_rtl_constraints_cl_send_to_rtl():

  class Source( ComponentLevel5 ):

    def construct( s, msgs ):
      s.msgs = deque( msgs )

      s.req     = CallerPort()
      s.req_rdy = CallerPort()

      s.v = 0
      @s.update
      def up_src():
        s.v = None
        if s.req_rdy() and s.msgs:
          s.v = s.msgs.popleft()
          s.req( s.v )

  class CL2RTL( ComponentLevel5 ):

    def construct( s ):
      s.send_rdy = InPort( Bits1 )
      s.send_en  = OutPort( Bits1 )
      s.send_msg = OutPort( Bits32 )

      s.entry = None

      @s.update
      def up_send_rtl():
        if s.entry is None:
          s.send_en  = Bits1( 0 )
          s.send_msg = Bits32( 0 )
        else:
          s.send_en  = s.send_rdy
          s.send_msg = s.entry

      s.add_constraints(
        M( s.recv_rdy ) < U( up_send_rtl ),
        M( s.recv ) < U( up_send_rtl )
      )

    @method_port
    def recv( s, msg ):
      s.msg_to_send = msg

    @method_port
    def recv_rdy( s ):
      return s.entry is None

  class DUT( ComponentLevel5 ):

    def construct( s ):
      s.recv_rdy = OutPort( Bits1 )
      s.recv_en  = InPort( Bits1 )
      s.recv_msg = InPort( Bits32 )

      @s.update
      def up_dut():
        s.recv_rdy = Bits1(1)
        print(s.recv_en, s.recv_msg)

  class Top( ComponentLevel5 ):
    def construct( s ):
      s.src = Source([1,2,3,4])
      s.adp = CL2RTL()( recv = s.src.req, recv_rdy = s.src.req_rdy )
      s.dut = DUT()( recv_rdy = s.adp.send_rdy,
                     recv_en  = s.adp.send_en,
                     recv_msg = s.adp.send_msg,
                    )
  x = Top()
  x.elaborate()
  from pymtl3.passes import DynamicSim
  for y in DynamicSim:
    y(x)

  x.tick()
  x.tick()
  x.tick()
  x.tick()

def test_mix_cl_rtl_constraints_rtl_send_to_cl():

  class Sink( ComponentLevel5 ):

    @method_port
    def recv_rdy( s ):
      return s.entry is None

    @method_port
    def recv( s, v ):
      s.entry = v

    def construct( s, msgs ):
      s.msgs  = list( msgs )
      s.entry = None
      s.idx  = 0

      @s.update
      def up_sink():
        if s.entry is not None:
          assert s.idx < len(s.msgs)
          ref = s.msgs[ s.idx ]
          s.idx += 1
          assert msg == ref
          s.entry = None

      s.add_constraints(
        U(up_sink) > M(s.recv    ),
        U(up_sink) > M(s.recv_rdy),
      )

  class RTL2CL( ComponentLevel5 ):

    def construct( s ):
      s.recv_rdy = OutPort( Bits1 )
      s.recv_en  = InPort( Bits1 )
      s.recv_msg = InPort( Bits32 )

      s.send     = CallerPort()
      s.send_rdy = CallerPort()

      @s.update
      def up_recv_rtl_rdy():
        s.recv_rdy = Bits1( 1 ) if s.send_rdy() else Bits1( 0 )

      @s.update
      def up_send_cl():
        if s.recv_en:
          s.send( s.recv_msg )

      s.add_constraints( U( up_recv_rtl_rdy ) < U( up_send_cl ) )

  class DUT( ComponentLevel5 ):

    def construct( s ):
      s.send_rdy = InPort ( Bits1 )
      s.send_en  = OutPort( Bits1 )
      s.send_msg = OutPort( Bits32 )

      @s.update
      def up_dut():
        if s.send_rdy:
          s.send_en  = Bits1( 1 )
          s.send_msg = Bits32( 100 )
        else:
          s.send_en  = Bits1( 0 )
          s.send_msg = Buts32( 0 )

  class Top( ComponentLevel5 ):
    def construct( s ):
      s.dut = DUT()
      s.adp = RTL2CL()( recv_rdy = s.dut.send_rdy,
                        recv_en  = s.dut.send_en,
                        recv_msg = s.dut.send_msg,
                      )
      s.sink = Sink([100,100,100,100])( recv = s.adp.send, recv_rdy = s.adp.send_rdy )

  x = Top()
  x.elaborate()
  simple_sim_pass( x )
