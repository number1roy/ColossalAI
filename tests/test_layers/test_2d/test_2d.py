#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from functools import partial

import pytest
import torch
import torch.multiprocessing as mp
from colossalai.core import global_context as gpc
from colossalai.initialize import launch
from colossalai.logging import disable_existing_loggers
from colossalai.utils import free_port
from colossalai.testing import rerun_on_exception
from checks_2d.check_layer_2d import (check_classifier_given_embed_weight, check_classifier_no_given_weight,
                                      check_embed, check_layernorm, check_linear, check_loss, check_patch_embed,
                                      check_vocab_parallel_classifier_given_embed_weight,
                                      check_vocab_parallel_classifier_no_given_weight, check_vocab_parallel_embed,
                                      check_vocab_parallel_loss)
from checks_2d.check_operation_2d import check_AB, check_ABT, check_ATB

CONFIG = dict(parallel=dict(pipeline=dict(size=1), tensor=dict(size=4, mode='2d')),)


def check_operations():
    check_AB()
    check_ABT()
    check_ATB()


def check_layer():
    check_linear()
    check_layernorm()
    check_embed()
    check_patch_embed()
    check_vocab_parallel_embed()
    check_classifier_no_given_weight()
    check_vocab_parallel_classifier_no_given_weight()
    check_classifier_given_embed_weight()
    check_vocab_parallel_classifier_given_embed_weight()
    check_loss()
    check_vocab_parallel_loss()


def check_layer_and_operation(rank, world_size, port):
    disable_existing_loggers()
    launch(config=CONFIG, rank=rank, world_size=world_size, host='localhost', port=port, backend='nccl')

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    # check_operations()
    check_layer()
    gpc.destroy()
    torch.cuda.empty_cache()


@pytest.mark.dist
@rerun_on_exception(exception_type=mp.ProcessRaisedException, pattern=".*Address already in use.*")
def test_2d():
    world_size = 4
    run_func = partial(check_layer_and_operation, world_size=world_size, port=free_port())
    mp.spawn(run_func, nprocs=world_size)


if __name__ == '__main__':
    test_2d()
