#=========================================================================
# BehavioralRTLIRGenL1Pass.py
#=========================================================================
# Author : Peitian Pan
# Date   : Oct 20, 2018
"""Provide L1 behavioral RTLIR generation pass."""

import ast
import copy

import pymtl3.dsl as dsl
from pymtl3.datatypes import Bits, concat, reduce_and, reduce_or, reduce_xor, sext, zext, \
    is_bitstruct_inst, is_bitstruct_class
from pymtl3.passes.BasePass import BasePass, PassMetadata
from pymtl3.passes.rtlir.errors import PyMTLSyntaxError
from pymtl3.passes.rtlir.util.utility import get_ordered_upblks, get_ordered_update_ff

from . import BehavioralRTLIR as bir


class BehavioralRTLIRGenL1Pass( BasePass ):
  def __call__( s, m ):
    """Generate RTLIR for all upblks of m."""
    if not hasattr( m, '_pass_behavioral_rtlir_gen' ):
      m._pass_behavioral_rtlir_gen = PassMetadata()

    m._pass_behavioral_rtlir_gen.rtlir_upblks = {}
    visitor = BehavioralRTLIRGeneratorL1( m )
    upblks = {
      'CombUpblk' : get_ordered_upblks(m),
      'SeqUpblk'  : get_ordered_update_ff(m),
    }
    # Sort the upblks by their name
    upblks['CombUpblk'].sort( key = lambda x: x.__name__ )
    upblks['SeqUpblk'].sort( key = lambda x: x.__name__ )

    for upblk_type in ( 'CombUpblk', 'SeqUpblk' ):
      for blk in upblks[ upblk_type ]:
        visitor._upblk_type = upblk_type
        upblk_info = m.get_update_block_info( blk )
        upblk = visitor.enter( blk, upblk_info[-1] )
        upblk.is_lambda = upblk_info[0]
        upblk.src       = upblk_info[1]
        upblk.lino      = upblk_info[2]
        upblk.filename  = upblk_info[3]
        m._pass_behavioral_rtlir_gen.rtlir_upblks[ blk ] = upblk

class BehavioralRTLIRGeneratorL1( ast.NodeVisitor ):
  def __init__( s, component ):
    s.component = component

  def enter( s, blk, ast ):
    """Entry point of RTLIR generation."""
    s.blk     = blk

    # s.globals contains a dict of the global namespace of the module where
    # blk was defined
    s.globals = blk.__globals__

    # s.closure contains the free variables defined in an enclosing scope.
    # Basically this is the model instance s.
    s.closure = {}

    for i, var in enumerate( blk.__code__.co_freevars ):
      try:
        s.closure[ var ] = blk.__closure__[ i ].cell_contents
      except ValueError:
        pass

    s.const_extractor = ConstantExtractor( s.blk, s.globals, s.closure )
    ret = s.visit( ast )
    ret.component = s.component
    return ret

  def handle_constant( s, node, obj ):
    if isinstance( obj, int ):
      return bir.Number( obj )
    elif isinstance( obj, Bits ):
      return bir.SizeCast( obj.nbits, bir.Number( obj.value ) )
    else:
      return None
    # else:
    #   raise PyMTLSyntaxError( s.blk, node,
    #       f"object {obj} cannot be converted to behavioral RTLIR!" )

  def get_call_obj( s, node ):
    if hasattr(node, "starargs") and node.starargs:
      raise PyMTLSyntaxError( s.blk, node, 'star argument is not supported!')
    if hasattr(node, "kwargs") and node.kwargs:
      raise PyMTLSyntaxError( s.blk, node,
        'double-star argument is not supported!')
    if node.keywords:
      raise PyMTLSyntaxError( s.blk, node, 'keyword argument is not supported!')
    if not isinstance( node.func, ast.Name ):
      raise PyMTLSyntaxError( s.blk, node,
        f'{node.func} is called but is not a name!')

    obj = s.const_extractor.enter( node.func )
    if obj is not None:
      return obj
    else:
      raise PyMTLSyntaxError( s.blk, node,
        node.func.id + ' function is not found!' )

  def visit_Module( s, node ):
    if len( node.body ) != 1 or \
        not isinstance( node.body[0], ast.FunctionDef ):
      raise PyMTLSyntaxError( s.blk, node,
        'Update blocks should have exactly one FuncDef!' )
    ret = s.visit( node.body[0] )
    ret.ast = node
    return ret

  def visit_FunctionDef( s, node ):
    """Return the behavioral RTLIR of function node.

    We do not need to check the decorator list -- the fact that we are
    visiting this node ensures this node was added to the upblk
    dictionary through s.update() (or other PyMTL decorators) earlier!
    """
    # Check the arguments of the function
    if node.args.args or node.args.vararg or node.args.kwarg:
      raise PyMTLSyntaxError( s.blk, node,
        'Update blocks should not have arguments!' )

    # Save the name of the upblk
    s._upblk_name = node.name

    # Get the type of upblk from ._upblk_type variable
    ret = eval( 'bir.' + s._upblk_type + '( node.name, [] )' )
    for stmt in node.body:
      ret.body.append( s.visit( stmt ) )
    ret.ast = node
    return ret

  def visit_Assign( s, node ):
    blocking = {
      'CombUpblk' : True,
      'SeqUpblk'  : False,
    }

    if len( node.targets ) < 1:
      raise PyMTLSyntaxError( s.blk, node,
        'At least one assignment target should be provided!' )

    if s._upblk_type not in blocking:
      raise PyMTLSyntaxError( s.blk, node,
        'Assignment should be in either a combinational or a sequential update block!' )

    value = s.visit( node.value )
    targets = [ s.visit( target ) for target in node.targets ]
    ret = bir.Assign( targets, value, blocking = blocking[s._upblk_type] )
    ret.ast = node
    return ret

  def visit_AugAssign( s, node ):
    """Return the behavioral RTLIR of a non-blocking assignment

    If the given AugAssign is not non-blocking assignment, throw PyMTLSyntaxError
    """
    if isinstance( node.op, ast.LShift ):
      value = s.visit( node.value )
      targets = [ s.visit( node.target ) ]
      ret = bir.Assign( targets, value, blocking = False )
      ret.ast = node
      return ret
    raise PyMTLSyntaxError( s.blk, node,
        'invalid operation: augmented assignment is not non-blocking assignment!' )

  def visit_Call( s, node ):
    """Return the behavioral RTLIR of method calls.

    Some data types are interpreted as function calls in the Python AST.
    Example: Bits4(2)
    These are converted to different RTLIR nodes in different contexts.
    """
    obj = s.get_call_obj( node )
    if ( obj == copy.copy ) or ( obj == copy.deepcopy ):
      if len( node.args ) != 1:
        raise PyMTLSyntaxError( s.blk, node,
          f'copy method {obj} takes exactly 1 argument!')
      ret = s.visit( node.args[0] )
      ret.ast = node
      return ret

    # Now that we have the live Python object, there are a few cases that
    # we need to treat separately:
    # 1. Instantiation: Bits16( 10 ) where obj is an instance of Bits
    # Bits16( 1+2 ), Bits16( s.STATE_A )?
    # 2. concat()
    # 3. zext(), sext()
    # TODO: support the following
    # 4. reduce_and(), reduce_or(), reduce_xor()
    # 5. Real function call: not supported yet

    # Deal with Bits type cast
    if isinstance(obj, type) and issubclass( obj, Bits ):
      nbits = obj.nbits
      if len( node.args ) != 1:
        raise PyMTLSyntaxError( s.blk, node,
          'exactly one argument should be given to Bits!' )
      value = s.visit( node.args[0] )
      ret = bir.SizeCast( nbits, value )
      ret.ast = node
      return ret

    # concat method
    elif obj is concat:
      if len( node.args ) < 1:
        raise PyMTLSyntaxError( s.blk, node,
          'at least one argument should be given to concat!' )
      values = [s.visit(c) for c in node.args]
      ret = bir.Concat( values )
      ret.ast = node
      return ret

    # zext method
    elif obj is zext:
      if len( node.args ) != 2:
        raise PyMTLSyntaxError( s.blk, node,
          'exactly two arguments should be given to zext!' )
      nbits = s.visit( node.args[1] )
      value = s.visit( node.args[0] )
      ret = bir.ZeroExt( nbits, value )
      ret.ast = node
      return ret

    # sext method
    elif obj is sext:
      if len( node.args ) != 2:
        raise PyMTLSyntaxError( s.blk, node,
          'exactly two arguments should be given to sext!' )
      nbits = s.visit( node.args[1] )
      value = s.visit( node.args[0] )
      ret = bir.SignExt( nbits, value )
      ret.ast = node
      return ret

    # reduce methods
    elif obj is reduce_and or obj is reduce_or or obj is reduce_xor:
      if obj is reduce_and:
        op = bir.BitAnd()
      elif obj is reduce_or:
        op = bir.BitOr()
      elif obj is reduce_xor:
        op = bir.BitXor()
      if len( node.args ) != 1:
        raise PyMTLSyntaxError( s.blk, node,
          f'exactly two arguments should be given to reduce {op} methods!' )
      value = s.visit( node.args[0] )
      ret = bir.Reduce( op, value )
      ret.ast = node
      return ret

    else:
      # Only Bits class instantiation is supported at L1
      raise PyMTLSyntaxError( s.blk, node,
        f'Unrecognized method call {obj.__name__}!' )

  def visit_Attribute( s, node ):
    obj = s.const_extractor.enter( node )
    ret = s.handle_constant( node, obj )
    if ret:
      return ret

    ret = bir.Attribute( s.visit( node.value ), node.attr )
    ret.ast = node
    return ret

  def visit_Subscript( s, node ):
    obj = s.const_extractor.enter( node )
    ret = s.handle_constant( node, obj )
    if ret:
      return ret

    value = s.visit( node.value )
    if isinstance( node.slice, ast.Slice ):
      if node.slice.step is not None:
        raise PyMTLSyntaxError( s.blk, node,
          'Slice with steps is not supported!' )
      lower, upper = s.visit( node.slice )
      ret = bir.Slice( value, lower, upper )
      ret.ast = node
      return ret

    # signal[ index ]
    # index might be a slice object!
    if isinstance( node.slice, ast.Index ):
      idx = s.visit( node.slice )
      # If we have a static slice object then use it
      if isinstance( idx, bir.FreeVar ) and isinstance( idx.obj, slice ):
        slice_obj = idx.obj
        if slice_obj.step is not None:
          raise PyMTLSyntaxError( s.blk, node,
            'Slice with steps is not supported!' )
        assert isinstance( slice_obj.start, int ) and \
               isinstance( slice_obj.stop, int ), \
            f"start and stop of slice object {slice_obj} must be integers!"
        ret = bir.Slice( value,
              bir.Number(slice_obj.start), bir.Number(slice_obj.stop) )
      # Else this is a real index
      else:
        ret = bir.Index( value, idx )
      ret.ast = node
      return ret

    raise PyMTLSyntaxError( s.blk, node,
      'Illegal subscript ' + node + ' encountered!' )

  def visit_Slice( s, node ):
    return ( s.visit( node.lower ), s.visit( node.upper ) )

  def visit_Index( s, node ):
    return s.visit( node.value )

  def visit_Name( s, node ):
    if node.id in s.closure:
      # free var from closure
      obj = s.closure[ node.id ]
      if isinstance( obj, dsl.Component ):
        # Component freevars are an L1 thing.
        if obj is not s.component:
          raise PyMTLSyntaxError( s.blk, node,
            f'Component {obj} is not a sub-component of {s.component}!' )
        ret = bir.Base( obj )
      else:
        # A closure variable could be a loop index. We need to
        # generate per-function closure variable instead of assuming
        # they will have the same value.
        ret =  bir.FreeVar( f"{node.id}_at_{s.blk.__name__}", obj )
      ret.ast = node
      return ret
    elif node.id in s.globals:
      # free var from the global name space
      # For now we can still safely assume all upblks will see the same
      # value for a free var from the global space?
      ret = bir.FreeVar( node.id, s.globals[ node.id ] )
      ret.ast = node
      return ret
    raise PyMTLSyntaxError( s.blk, node,
      f'Temporary variable {node.id} is not supported at L1!' )

  def visit_Num( s, node ):
    ret = bir.Number( node.n )
    ret.ast = node
    return ret

  def visit_If( s, node ): raise NotImplementedError()

  def visit_For( s, node ): raise NotImplementedError()

  def visit_BoolOp( s, node ): raise NotImplementedError()

  def visit_BinOp( s, node ): raise NotImplementedError()

  def visit_UnaryOp( s, node ): raise NotImplementedError()

  def visit_IfExp( s, node ): raise NotImplementedError()

  def visit_Compare( s, node ): raise NotImplementedError()

  # $display
  def visit_Print( s, node ): raise NotImplementedError()

  # function
  def visit_Return( s, node ): raise NotImplementedError()

  # SV assertion
  def visit_Assert( s, node ): raise NotImplementedError()

  def visit_Expr( s, node ):
    """Return the behavioral RTLIR of an expression.

    ast.Expr might be useful when a statement is only a call to a task or
    a non-returning function.
    """
    raise PyMTLSyntaxError(
      s.blk, node, 'Stand-alone expression is not supported yet!' )

  def visit_Lambda( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: lambda function' )

  def visit_Dict( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid type: dict' )

  def visit_Set( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid type: set' )

  def visit_List( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid type: list' )

  def visit_Tuple( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid type: tuple' )

  def visit_ListComp( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: list comprehension' )

  def visit_SetComp( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: set comprehension' )

  def visit_DictComp( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: dict comprehension' )

  def visit_GeneratorExp( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: generator expression' )

  def visit_Yield( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: yield' )

  def visit_Repr( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: repr' )

  def visit_Str( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: str' )

  def visit_ClassDef( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: classdef' )

  def visit_Delete( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: delete' )

  def visit_With( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: with' )

  def visit_Raise( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: raise' )

  def visit_TryExcept( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: try-except' )

  def visit_TryFinally( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: try-finally' )

  def visit_Import( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: import' )

  def visit_ImportFrom( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: import-from' )

  def visit_Exec( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: exec' )

  def visit_Global( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: global' )

  def visit_Pass( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: pass' )

  def visit_Break( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: break' )

  def visit_Continue( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: continue' )

  def visit_While( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: while' )

  def visit_ExtSlice( s, node ):
    raise PyMTLSyntaxError( s.blk, node, 'invalid operation: extslice' )

class ConstantExtractor( ast.NodeVisitor ):
  def __init__( s, blk, global_ns, closure_ns ):
    s.blk = blk
    s.globals = global_ns
    s.closure = closure_ns

  def generic_visit( s, node ):
    return None

  def enter( s, node ):
    ret = s.visit( node )
    if ret is not None and \
       (isinstance(ret, (int, Bits)) or \
       (isinstance(ret, type) and issubclass(ret, Bits)) or \
       is_bitstruct_inst or is_bitstruct_class):
      return ret
    else:
      return None

  def visit_Attribute( s, node ):
    if hasattr( node, '_constant_extractor_value' ):
      return node._constant_extractor_value
    value = s.visit( node.value )
    try:
      ret = getattr( value, node.attr )
    except AttributeError:
      ret = None
    node._constant_extractor_value = ret
    return ret

  def visit_Subscript( s, node ):
    if hasattr( node, '_constant_extractor_value' ):
      return node._constant_extractor_value
    ret = None
    if isinstance( node.slice, ast.Index ):
      value = s.visit( node.value )
      idx = s.visit( node.slice )
      if value is not None and idx is not None:
        try:
          ret = value[idx]
        except TypeError:
          ret = None
    node._constant_extractor_value = ret
    return ret

  def visit_Index( s, node ):
    if hasattr( node, '_constant_extractor_value' ):
      return node._constant_extractor_value
    ret = s.visit( node.value )
    node._constant_extractor_value = ret
    return ret

  def visit_Name( s, node ):
    name = node.id
    if name in s.closure:
      # free var from closure
      obj = s.closure[ name ]
    elif name in s.globals:
      # free var from the global name space
      obj = s.globals[ name ]
    else:
      obj = None
    return obj

  def visit_Num( s, node ):
    return node.n
