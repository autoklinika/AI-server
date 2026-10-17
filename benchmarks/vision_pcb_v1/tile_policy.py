"""Deterministic high-resolution image tiling for WinCLIP Vision PCB B1.

Geometry only: no PIL, torch or network dependency. Coordinates refer to
original pixels. Tile scores are aggregated as a max, with calibration
recomputed independently for each preprocessing mode.
"""
from __future__ import annotations

def axis_positions(length: int, tile_size: int, overlap: float) -> list[int]:
    if not isinstance(length,int) or length < 1:
        raise ValueError("positive integer length required")
    if not isinstance(tile_size,int) or tile_size < 128:
        raise ValueError("tile_size >=128 required")
    if not 0 <= overlap < .75:
        raise ValueError("overlap must be 0 <= value < 0.75")
    if length <= tile_size:
        return [0]
    stride = max(1,int(tile_size * (1-overlap)))
    positions=list(range(0, length-tile_size+1, stride))
    last=length-tile_size
    if not positions or positions[-1] != last:
        positions.append(last)
    return positions

def tile_rectangles(width: int,height: int,tile_size: int=640,overlap: float=0.25)->list[tuple[int,int,int,int]]:
    xs=axis_positions(width,tile_size,overlap)
    ys=axis_positions(height,tile_size,overlap)
    rectangles=[]
    for y in ys:
        for x in xs:
            rectangles.append((x,y,min(width,x+tile_size),min(height,y+tile_size)))
    if len(rectangles)>256:
        raise ValueError("too many tiles: reduce overlap or enlarge tile_size")
    return rectangles

def aggregate_max(global_score:float,tile_scores:list[float])->float:
    vals=[global_score,*tile_scores]
    if not vals or any(not isinstance(s,(float,int)) or not 0 <= s <=1 for s in vals):
        raise ValueError("scores must be finite in [0,1]")
    return max(vals)
