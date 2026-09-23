#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class Bar:
    time:int; high:float; low:float; close:float
def excursion(*,bars:list[Bar],reference_price:float,direction:str,cost:float=0.0)->dict:
    if not bars:raise ValueError("bars required")
    if direction not in {"BUY","SELL"}:raise ValueError("direction")
    if direction=="BUY":
        fav=[b.high-reference_price for b in bars];adv=[reference_price-b.low for b in bars]
    else:
        fav=[reference_price-b.low for b in bars];adv=[b.high-reference_price for b in bars]
    i_f=max(range(len(fav)),key=fav.__getitem__);i_a=max(range(len(adv)),key=adv.__getitem__)
    return {"mfe_price":max(fav)-cost,"mae_price":max(adv)+cost,"time_to_mfe":bars[i_f].time-bars[0].time,
            "time_to_mae":bars[i_a].time-bars[0].time,"observation_start_time":bars[0].time,"observation_end_time":bars[-1].time}
def assert_post_availability(*,setup_availability_time:int,bars:list[Bar])->None:
    if any(b.time<setup_availability_time for b in bars):raise ValueError("pre-availability bar in outcome window")
