import os
from functools import partial
from pathlib import Path

import colossalai
import pytest
import torch
import torch.multiprocessing as mp
import torch.nn as nn
from colossalai.core import global_context as gpc
from colossalai.logging import get_dist_logger
from colossalai.utils import free_port, get_dataloader
from colossalai.testing import rerun_on_exception
from torch.optim import Adam
from torchvision import transforms
from torchvision.datasets import CIFAR10
from torchvision.models import resnet18

# Config
BATCH_SIZE = 2
NUM_CLASSES = 10

CONFIG = dict(parallel=dict(pipeline=dict(size=1), tensor=dict(size=1, mode=None)),
              clip_grad_norm=1.0,
              gradient_accumulation=4)


def run_no_pipeline(rank, world_size, port):

    # init dist env
    colossalai.launch(config=CONFIG, rank=rank, world_size=world_size, host='localhost', port=port, backend='nccl')

    # build model
    model = resnet18(num_classes=10)

    # build dataloaders
    train_dataset = CIFAR10(root=Path(os.environ['DATA']),
                            download=True,
                            transform=transforms.Compose([
                                transforms.ToTensor(),
                                transforms.Normalize(mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))
                            ]))
    train_dataloader = get_dataloader(dataset=train_dataset,
                                      shuffle=True,
                                      batch_size=BATCH_SIZE,
                                      pin_memory=True,
                                      drop_last=True)

    # build optimizer
    optimizer = Adam(model.parameters(), lr=0.001)
    criterion = nn.CrossEntropyLoss()

    engine, train_dataloader, *args = colossalai.initialize(model=model,
                                                            optimizer=optimizer,
                                                            criterion=criterion,
                                                            train_dataloader=train_dataloader)
    logger = get_dist_logger()
    rank = torch.distributed.get_rank()
    param_track = []
    grad_track = []
    next(model.parameters()).retain_grad()

    engine.train()
    step = 0
    for img, label in train_dataloader:
        engine.zero_grad()
        img = img.cuda()
        label = label.cuda()
        output = engine(img)
        loss = engine.criterion(output, label)
        engine.backward(loss)
        engine.step()

        # check
        param_track.append(next(model.parameters())[0].clone())
        grad_track.append(next(model.parameters()).grad[0].clone())
        step += 1
        if step == CONFIG['gradient_accumulation']:
            break

    assert not torch.all(grad_track[0] == grad_track[-1]), 'grad should be different in different iterations'
    assert torch.all(param_track[0] == param_track[1]) and not torch.all(param_track[0] == param_track[-1]), \
        'param should be the same in the first few iterations and only changed in the last iteration'

    gpc.destroy()
    torch.cuda.empty_cache()


@pytest.mark.dist
@rerun_on_exception(exception_type=mp.ProcessRaisedException, pattern=".*Address already in use.*")
def test_engine():
    world_size = 4
    func = partial(run_no_pipeline, world_size=world_size, port=free_port())
    mp.spawn(func, nprocs=world_size)


if __name__ == '__main__':
    test_engine()
