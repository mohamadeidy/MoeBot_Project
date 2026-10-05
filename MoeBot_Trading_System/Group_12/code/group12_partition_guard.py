#!/usr/bin/env python3
from __future__ import annotations
def chronological_partition(*,availability_time:int,discovery_end:int,confirmation_start:int)->str:
    if confirmation_start<=discovery_end:raise ValueError("partitions must have a strict temporal gap/boundary")
    if availability_time<=discovery_end:return "DISCOVERY"
    if availability_time>=confirmation_start:return "CONFIRMATION"
    return "PURGE_GAP"
def assert_partition_disjoint(discovery_ids:set[str],confirmation_ids:set[str])->None:
    overlap=discovery_ids & confirmation_ids
    if overlap:raise ValueError(f"partition overlap:{len(overlap)}")
