from sqlalchemy import true
import torch
from utils import save_checkpoint, load_checkpoint
from utils import save_some_examples
import torch.nn as nn
import torch.optim as optim
import config
from PIL import Image
from  pytorch_msssim import MS_SSIM
from costumDataset import Kaiset,depthset
import sys
#chooses what model to train
if config.MODEL == "ResUnet":
    from resUnet import Generator
else:
    from generator_model import Generator
from matplotlib import pyplot as plt

from discriminator_model import Discriminator
from torch.utils.data import DataLoader
from tqdm import tqdm
from torch.utils.tensorboard import SummaryWriter
from time import localtime
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
from piqa import GMSD
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

if not os.path.exists("evaluation"):
    os.mkdir("evaluation")


torch.backends.cudnn.benchmark = True


def train_fn(
    disc, gen, loader, opt_disc, opt_gen, l1_loss,loss, bce, criterion, g_scaler, d_scaler,writer, epoch=0
):
    loop = tqdm(loader, leave=True)

    for idx, (x, y) in enumerate(loop):
        x = x.to(config.DEVICE)
        y = y.to(config.DEVICE)

        # Train Discriminator
        with torch.cuda.amp.autocast():
            y_fake = gen(x)
            D_real = disc(x, y)
            D_real_loss = bce(D_real, torch.ones_like(D_real))
            D_fake = disc(x, y_fake.detach())
            D_fake_loss = bce(D_fake, torch.zeros_like(D_fake))
            D_loss = (D_real_loss + D_fake_loss) / 2

        disc.zero_grad()
        d_scaler.scale(D_loss).backward()
        d_scaler.step(opt_disc)
        d_scaler.update()

        # Train generator
        with torch.cuda.amp.autocast():
            D_fake = disc(x, y_fake)
            G_fake_loss = bce(D_fake, torch.ones_like(D_fake))

            # fake_gradient=g(y_fake[:,0,:,:])
            # real_gradient=g(y[:,0,:,:])


            with torch.no_grad():
                plusloss= int(sys.argv[3]) * criterion(y_fake * 0.5 + 0.5 ,y * 0.5 + 0.5 )
                L1 = l1_loss(y_fake, y) * int(sys.argv[3])
                _SSIM = (1 - loss((y_fake.double() + 1) / 2, (y.double() + 1) / 2)) * int(sys.argv[3])
            G_loss = G_fake_loss + L1 + _SSIM + plusloss

        opt_gen.zero_grad()
        g_scaler.scale(G_loss).backward()
        g_scaler.step(opt_gen)
        g_scaler.update()

        if idx % 10 == 0:
            writer.add_scalar("L1 train loss",L1.item()/int(sys.argv[3]),epoch*(len(loop))+idx)
            writer.add_scalar("SSIM train loss",_SSIM.item()/int(sys.argv[3]),epoch*(len(loop))+idx)
            writer.add_scalar("GMSD train loss",plusloss.item()/int(sys.argv[3]),epoch*(len(loop))+idx)
            writer.add_scalar("D_real train loss", torch.sigmoid(D_real).mean().item(), epoch * (len(loop)) + idx)
            writer.add_scalar("D_fake train loss", torch.sigmoid(D_fake).mean().item(), epoch * (len(loop)) + idx)
            loop.set_postfix(
                D_real=torch.sigmoid(D_real).mean().item(),
                D_fake=torch.sigmoid(D_fake).mean().item(),
                L1 =L1.item()/int(sys.argv[3]),
                GMSD = plusloss.item()/int(sys.argv[3]),
                SSIM = _SSIM.item()/int(sys.argv[3])
            )
def test_fn(
    disc, gen, loader, l1_loss, loss, bce, criterion, writer, epoch=0
):
    loop = tqdm(loader, leave=True)
    disc.eval()
    gen.eval()
    with torch.no_grad():
     resultat=[]
     for idx, (x, y) in enumerate(loop):
        x = x.to(config.DEVICE)
        y = y.to(config.DEVICE)

        # Train Discriminator
        with torch.cuda.amp.autocast():
            y_fake = gen(x)
            D_real = disc(x, y)
            D_real_loss = bce(D_real, torch.ones_like(D_real))
            D_fake = disc(x, y_fake.detach())
            D_fake_loss = bce(D_fake, torch.zeros_like(D_fake))
            D_loss = (D_real_loss + D_fake_loss) / 2



        # Train generator
        with torch.cuda.amp.autocast():
            D_fake = disc(x, y_fake)
            plusloss= int(sys.argv[3]) * criterion(y_fake * 0.5 + 0.5 ,y * 0.5 + 0.5 )
            L1 = l1_loss(y_fake, y) * int(sys.argv[3])
            _SSIM = (1 - loss((y_fake.double() + 1) / 2, (y.double() + 1) / 2)) * int(sys.argv[3])
            resultat.append(L1.item())



        if idx % 10 == 0:
            writer.add_scalar("L1 test loss",L1.item()/config.L1_LAMBDA,epoch*(len(loop))+idx)
            writer.add_scalar("SSIM test loss",_SSIM.item()/config.L1_LAMBDA,epoch*(len(loop))+idx)
            writer.add_scalar("GMSD test loss",plusloss.item()/config.L1_LAMBDA,epoch*(len(loop))+idx)
            writer.add_scalar("D_real test loss", torch.sigmoid(D_real).mean().item(), epoch * (len(loop)) + idx)
            writer.add_scalar("D_fake test loss", torch.sigmoid(D_fake).mean().item(), epoch * (len(loop)) + idx)
            loop.set_postfix(
                D_real=torch.sigmoid(D_real).mean().item(),
                D_fake=torch.sigmoid(D_fake).mean().item(),
                L1 =L1.item()/int(sys.argv[3]),
                GMSD = plusloss.item()/int(sys.argv[3]),
                SSIM = _SSIM.item()/int(sys.argv[3])
            )
    disc.train()
    gen.train()
    return torch.tensor(resultat).mean()
def main():
    #instancing the models
    disc = Discriminator(in_channels=3).to(config.DEVICE)
    #print(disc)
    gen = Generator(init_weight=config.INIT_WEIGHTS).to(config.DEVICE)
    #print(gen)
    #instancing the optims
    opt_disc = optim.Adam(disc.parameters(), lr=config.LEARNING_RATE*float(sys.argv[8]), betas=(0.5, 0.999))
    opt_gen = optim.Adam(gen.parameters(), lr=config.LEARNING_RATE*float(sys.argv[8]), betas=(0.5, 0.999))
    writer=SummaryWriter("train{}-{}".format(localtime().tm_mon,localtime().tm_mday))
    #schedulergen = torch.optim.lr_scheduler.ExponentialLR(opt_gen , gamma=0.1)
    #schedulerdisc = torch.optim.lr_scheduler.ExponentialLR(opt_disc, gamma=0.1)
    #instancing the Loss-functions
    BCE = nn.BCEWithLogitsLoss()
    L1_LOSS = nn.L1Loss()
    Loss = MS_SSIM(data_range=1, size_average=True, channel=3, win_size=11)
    criterion = GMSD().cuda()
    

    #if true loads the checkpoit in the ./
    if sys.argv[6]!="none":
        load_checkpoint(
            sys.argv[6], gen, opt_gen, config.LEARNING_RATE,
        )
    if sys.argv[7]!="none":
        load_checkpoint(
            sys.argv[7], disc, opt_disc, config.LEARNING_RATE,
        )

    #training data loading

    train_dataset = Kaiset(path=sys.argv[1], Listset=config.DTRAIN_LIST if sys.argv[5]=="0"else config.NTRAIN_LIST)
    train_loader = DataLoader(
        train_dataset,
        batch_size=int(sys.argv[4]),
        shuffle=True,
        num_workers=config.NUM_WORKERS,
    )
    test_dataset = Kaiset(path=sys.argv[1],train=False, Listset=config.DTRAIN_LIST if sys.argv[5]=="0"else config.NTRAIN_LIST)
    test_loader = DataLoader(
        test_dataset,
        batch_size=int(sys.argv[4]),
        shuffle=True,
        num_workers=config.NUM_WORKERS,
    )
    eval_dataset = Kaiset(path=sys.argv[1],train=False, Listset=config.DTRAIN_LIST if sys.argv[5]=="0"else config.NTRAIN_LIST, shuffle=True)
    eval_loader = DataLoader(
        eval_dataset,
        batch_size=int(sys.argv[4]),
        shuffle=False,
        num_workers=config.NUM_WORKERS,
    )
    #enabling MultiPrecision Mode, the optimise performance
    g_scaler = torch.cuda.amp.GradScaler()
    d_scaler = torch.cuda.amp.GradScaler()

    #evauation data loading
    best=10000000
    resultat=1
    for epoch in range(int(sys.argv[9])):
        train_fn(
           disc, gen, train_loader, opt_disc, opt_gen, L1_LOSS, Loss, BCE, criterion, g_scaler, d_scaler,writer,epoch=epoch
        )
        resultat=test_fn(disc, gen, test_loader,  L1_LOSS, Loss, BCE, criterion, writer, epoch=epoch)
        if best>resultat:
            print("improvement of the loss from {} to {}\n\n\n".format(best,resultat))
            best = resultat
        save_checkpoint(gen, opt_gen, epoch, filename=config.CHECKPOINT_GEN)
        save_checkpoint(disc, opt_disc, epoch, filename=config.CHECKPOINT_DISC)

        save_some_examples(gen, eval_loader, epoch, folder="evaluation")
        #schedulergen.step()
        #schedulerdisc.step()
        #print("lr generateur",opt_gen.param_groups[0]["lr"])
        #print("lr discriminateur", opt_gen.param_groups[0]["lr"])


if __name__ == "__main__":
    main()


