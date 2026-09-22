#!/usr/bin/env python3
from __future__ import annotations
ACTIONS={"WAIT","BUY","SELL","HOLD","EXIT"}
def validate_splits(*,train:set[str],validation:set[str],final_holdout:set[str])->None:
    if train&validation or train&final_holdout or validation&final_holdout:raise ValueError("partition overlap")
def validate_action(action:str)->None:
    if action not in ACTIONS:raise ValueError("unsupported action")
def training_manifest(*,train_ids:set[str],validation_ids:set[str],final_holdout_ids:set[str])->dict:
    validate_splits(train=train_ids,validation=validation_ids,final_holdout=final_holdout_ids)
    return {"train_count":len(train_ids),"validation_count":len(validation_ids),"final_holdout_count":len(final_holdout_ids),
            "final_holdout_accessed":False,"action_vocabulary":sorted(ACTIONS)}
