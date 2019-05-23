#=========================================================================
# BehavioralTranslatorL5_test.py
#=========================================================================
# Author : Peitian Pan
# Date   : May 20, 2019
"""Test the level 5 ehavioral translator."""

from __future__ import absolute_import, division, print_function

import pymtl.passes.rtlir.RTLIRDataType as rdt
import pymtl.passes.rtlir.RTLIRType as rt
from pymtl import *
from pymtl.passes.rtlir.test_utility import do_test
from pymtl.passes.rtlir.translation.behavioral.BehavioralTranslatorL5 import (
    BehavioralTranslatorL5,
)

from .TestBehavioralTranslator import mk_TestBehavioralTranslator


def local_do_test( m ):
  tr = mk_TestBehavioralTranslator(BehavioralTranslatorL5)(m)
  tr.translate_behavioral( m )
  for component, _ref_upblk_repr in m._ref_upblk_repr.iteritems():
    upblk_src = tr.behavioral.upblk_srcs[component]
    assert upblk_src == _ref_upblk_repr
  for component, _ref_freevar_repr in m._ref_freevar_repr.iteritems():
    decl_freevars = tr.behavioral.decl_freevars[component]
    assert decl_freevars == _ref_freevar_repr
  for component, _ref_tmpvar_repr in m._ref_tmpvar_repr.iteritems():
    decl_tmpvars = tr.behavioral.decl_tmpvars[component]
    assert decl_tmpvars == _ref_tmpvar_repr

def test_multi_components_tmpvars( do_test ):
  class B( Component ):
    def construct( s ):
      s.out = OutPort( Bits16 )
      @s.update
      def upblk():
        u = Bits16(0)
        s.out = u
  class A( Component ):
    def construct( s ):
      s.b = B()
      s.out = OutPort( Bits16 )
      @s.update
      def upblk():
        u = s.b.out
        s.out = u
  a = A()
  a.elaborate()
  a._ref_upblk_repr = { a : \
"""\
upblk_decls:
  upblk_decl: upblk
""", a.b : \
"""\
upblk_decls:
  upblk_decl: upblk
""" }
  a._ref_freevar_repr = { a : "freevars:\n", a.b : "freevars:\n" }
  a._ref_tmpvar_repr = { a : \
"""\
tmpvars:
  tmpvar: u in upblk of Vector16
""", a.b : \
"""\
tmpvars:
  tmpvar: u in upblk of Vector16
""" }
  do_test( a )

def test_multi_components_freevars( do_test ):
  STATE_IDLE = 0
  STATE_WORK = 1
  class B( Component ):
    def construct( s ):
      s.out = OutPort( Bits16 )
      @s.update
      def upblk():
        if 1:
          s.out = STATE_IDLE
        else:
          s.out = STATE_WORK
  class A( Component ):
    def construct( s ):
      s.b = B()
      s.out = OutPort( Bits16 )
      @s.update
      def upblk():
        if 1:
          s.out = s.b.out
        else:
          s.out = STATE_IDLE
  a = A()
  a.elaborate()
  a._ref_upblk_repr = { a : \
"""\
upblk_decls:
  upblk_decl: upblk
""", a.b : \
"""\
upblk_decls:
  upblk_decl: upblk
""" }
  a._ref_freevar_repr = { a.b : \
"""\
freevars:
  freevar: STATE_IDLE
  freevar: STATE_WORK
""", a : \
"""\
freevars:
  freevar: STATE_IDLE
""" }
  a._ref_tmpvar_repr = {}
  do_test( a )
