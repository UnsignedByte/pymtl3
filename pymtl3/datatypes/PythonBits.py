"""
========================================================================
Bits.py
========================================================================
Pure-Python implementation of fixed-bitwidth data type.

Author : Shunning Jiang
Date   : Oct 31, 2017
"""

# lower <= value <= upper
_upper = [ 0,  1 ]
_lower = [ 0, -1 ]

for i in range(2, 1024):
  _upper.append( (_upper[i-1] << 1) + 1 )
  _lower.append(  _lower[i-1] << 1      )

def _new_valid_bits( nbits, _uint ):
  ret = object.__new__( Bits )
  ret.nbits = nbits
  ret._uint = _uint
  return ret

class Bits:
  __slots__ = ( "nbits", "_uint" )

  def __init__( self, nbits=32, v=0, trunc=False ):
    assert 0 < nbits < 1024, "Only support 0 < nbits < 1024!"
    self.nbits = nbits

    # Trunc -- always use the int value
    if trunc:
      self._uint = int(v) & _upper[nbits]

    else: # Not trunc
      if isinstance( v, Bits ):
        if nbits < v.nbits:
          raise ValueError( f"Without truncation, a Bits{v.nbits} object "\
                            f"is too wide to be used to construct Bits{nbits}!" )
        self._uint = v._uint # no need to AND anymore
      else:
        v = int(v)
        lo = _lower[nbits]
        up = _upper[nbits]

        if v < lo or v > up:
          raise ValueError( f"Value {hex(v)} is too big for Bits{nbits}!\n" \
                            f"({v.bit_length() + (v < 0)} bits are needed in two's complement.)" )
        self._uint = v & up

  # PyMTL simulation specific

  def __ilshift__( self, v ):
    nbits = self.nbits
    try:
      # Bits/Bitstruct
      if nbits < v.nbits:
         raise ValueError( f"Bitwidth of LHS must be larger than or equal to (>=) RHS during <<= non-blocking assignment, " \
                           f"but here LHS Bits{nbits} < RHS Bits{v.nbits}" )
      self._next = v.to_bits()._uint
    except AttributeError:
      # Cast to int
      v = int(v)
      lo = _lower[nbits]
      up = _upper[nbits]

      if v < lo or v > up:
        raise ValueError( f"Value {hex(v)} is too big for Bits{nbits}!\n" \
                          f"({v.bit_length() + (v < 0)} bits are needed in two's complement.)" )
      self._next = v & up

    return self

  def _flip( self ):
    self._uint = self._next

  def clone( self ):
    return _new_valid_bits( self.nbits, self._uint )

  def __deepcopy__( self, memo ):
    return _new_valid_bits( self.nbits, self._uint )

  def __matmul__( self, other ):
    raise NotImplementedError

  def __imatmul__( self, v ):
    nbits = self.nbits
    try:
      # Bits/Bitstruct
      if v.nbits > nbits:
        raise ValueError( f"Bitwidth of LHS must be larger than or equal to RHS during @= blocking assignment, " \
                          f"but here LHS Bits{nbits} < RHS Bits{v.nbits}" )
      self._uint = v.to_bits()._uint
    except AttributeError:
      # Cast to int
      v = int(v)

      lo = _lower[nbits]
      up = _upper[nbits]

      if v < lo or v > up:
        raise ValueError( f"Value {hex(v)} is too big for Bits{nbits}!\n" \
                          f"({v.bit_length() + (v < 0)} bits are needed in two's complement.)" )
      self._uint = v & up

    return self

  def to_bits( self ):
    return self

  # Arithmetics
  def __getitem__( self, idx ):

    if isinstance( idx, slice ):
      if idx.step:
        raise IndexError( "Index cannot contain step" )
      try:
        start, stop = int(idx.start or 0), int(idx.stop or self.nbits)
        assert start < stop and start >= 0 and stop <= self.nbits
      except Exception:
        raise IndexError( f"Invalid access: [{idx.start}:{idx.stop}] in a Bits{self.nbits} instance" )

      # Bypass check
      nbits = stop - start
      return _new_valid_bits( stop-start, (self._uint >> start) & _upper[nbits] )

    i = int(idx)
    if i >= self.nbits or i < 0:
      raise IndexError( f"Invalid access: [{i}] in a Bits{self.nbits} instance" )

    # Bypass check
    return _new_valid_bits( 1, (self._uint >> i) & 1 )

  def __setitem__( self, idx, v ):
    sv = int(self._uint)

    if isinstance( idx, slice ):
      if idx.step:
        raise IndexError( "Index cannot contain step" )
      try:
        start, stop = int(idx.start or 0), int(idx.stop or self.nbits)
        assert start < stop and start >= 0 and stop <= self.nbits
      except Exception:
        raise IndexError( f"Invalid access: [{idx.start}:{idx.stop}] in a Bits{self.nbits} instance" )

      slice_nbits = stop - start
      if isinstance( v, Bits ):
        if v.nbits > slice_nbits:
          raise ValueError( f"Cannot fit {v} into a Bits{slice_nbits} slice" )

        self._uint = (sv & (~((1 << stop) - (1 << start)))) | \
                     ((v._uint & _upper[slice_nbits]) << start)
      else:
        # Cast to int
        v = int(v)
        lo = _lower[slice_nbits]
        up = _upper[slice_nbits]

        if v < lo or v > up:
          raise ValueError( f"Cannot fit {v} into a Bits{slice_nbits} slice\n" \
                            f"({v.bit_length() + (v < 0)} bits are needed in two's complement.)" )

        self._uint = (sv & (~((1 << stop) - (1 << start)))) | \
                     ((v & _upper[slice_nbits]) << start)
      return

    i = int(idx)
    if i >= self.nbits or i < 0:
      raise IndexError( f"Invalid access: [{i}] in a Bits{self.nbits} instance" )

    if isinstance( v, Bits ):
      if v.nbits > 1:
        raise ValueError( f"Without truncation, a Bits{v.nbits} object "\
                          f"is too wide to be used to construct Bits{nbits}!" )
      self._uint = (sv & ~(1 << i)) | ((v.nbits & 1) << i)
    else:
      v = int(v)
      if abs(v) > 1:
        raise ValueError( f"Value {hex(v)} is too big for 1-bit slice!\n" \
                          f"({v.bit_length() + (v < 0)} bits are needed in two's complement.)" )
      self._uint = (sv & ~(1 << i)) | ((int(v) & 1) << i)

  def __add__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint + other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint + other) & up )

  def __radd__( self, other ):
    return self.__add__( other )

  def __sub__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint - other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint - other) & up )

  def __rsub__( self, other ):
    return Bits( self.nbits, other ) - self

  def __mul__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint * other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint * other) & up)

  def __rmul__( self, other ):
    return self.__mul__( other )

  def __and__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint & other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint & other) & up)

  def __rand__( self, other ):
    return self.__and__( other )

  def __or__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint | other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint | other) & up)

  def __ror__( self, other ):
    return self.__or__( other )

  def __xor__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint ^ other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint ^ other) & up)

  def __rxor__( self, other ):
    return self.__xor__( other )

  def __floordiv__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint // other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint // other) & up)

  def __mod__( self, other ):
    try:
      nbits = max(self.nbits, other.nbits)
      return _new_valid_bits( nbits, (self._uint % other._uint) & _upper[nbits] )
    except:
      other = int(other)
      up = _upper[ self.nbits ]
      assert 0 <= other <= up
      return _new_valid_bits( self.nbits, (self._uint % other) & up)

  def __invert__( self ):
    nbits = self.nbits
    return _new_valid_bits( nbits, ~self._uint & _upper[nbits] )

  def __lshift__( self, other ):
    other = int(other)
    if other >= self.nbits:
      return _new_valid_bits( self.nbits, 0 )
    return Bits( self.nbits, self._uint << other, trunc=True )

  def __rshift__( self, other ):
    return _new_valid_bits( self.nbits, self._uint >> int(other) )

  def __eq__( self, other ):
    try:
      other = int(other)
    except Exception:
      return _new_valid_bits( 1, 0 )
    assert other >= 0

    return _new_valid_bits( 1, self._uint == other )

  # def __ne__( self, other ):
    # try:
      # other = int(other)
    # except ValueError:
      # return True
    # return Bits( 1, int(self._uint) != other )

  def __lt__( self, other ):
    other = int(other)
    assert other >= 0

    return _new_valid_bits( 1, self._uint < other )

  def __le__( self, other ):
    other = int(other)
    assert other >= 0

    return _new_valid_bits( 1, self._uint <= other )

  def __gt__( self, other ):
    other = int(other)
    assert other >= 0

    return _new_valid_bits( 1, self._uint > other )

  def __ge__( self, other ):
    other = int(other)
    assert other >= 0

    return _new_valid_bits( 1, self._uint >= other )

  def __bool__( self ):
    return self._uint != 0

  def __int__( self ):
    return self._uint

  def int( self ):
    if self._uint >> (self.nbits - 1):
      return -int(~self + 1)
    return self._uint

  def uint( self ):
    return self._uint

  def __index__( self ):
    return self._uint

  def __hash__( self ):
    return hash((self.nbits, self._uint))

  # Print

  def __repr__(self):
    return "Bits{}(0x{})".format( self.nbits, "{:x}".format(int(self._uint)).zfill(((self.nbits-1)>>2)+1) )

  def __str__(self):
    str = "{:x}".format(int(self._uint)).zfill(((self.nbits-1)>>2)+1)
    return str

  def __oct__( self ):
    # print("DEPRECATED: Please use .oct()!")
    return self.oct()

  def __hex__( self ):
    # print("DEPRECATED: Please use .hex()!")
    return self.hex()

  def bin(self):
    str = "{:b}".format(int(self._uint)).zfill(self.nbits)
    return "0b"+str

  def oct( self ):
    str = "{:o}".format(int(self._uint)).zfill(((self.nbits-1)>>1)+1)
    return "0o"+str

  def hex( self ):
    str = "{:x}".format(int(self._uint)).zfill(((self.nbits-1)>>2)+1)
    return "0x"+str
