# This will be useful for training on CIFAR dataset

#important imports
# install torch from here https://pytorch.org/ 
import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms
import os
import argparse
import sys
from tqdm import tqdm
sys.path.append(os.path.abspath('..'))
from patch_producer import PatchProducer
from mammogram_dataset import MammogramDataset
from progress_bar import progress_bar
from sklearn.metrics import balanced_accuracy_score
from training_functions import get_dataset, get_model
from CustomVIT import vit_b_16, vit_b_16_faster


def train(epoch, max_epochs, net, patch_producer, trainloader, optimizer, scheduler, criterion, device, cosine=False):
    net.train()
    train_loss = 0
    all_preds = []
    all_targets = []
    
    for batch_idx, (inputs, targets, meta) in enumerate(trainloader):
        inputs, targets, meta = inputs.to(device), targets.to(device), meta.to(device)
        optimizer.zero_grad()
        patch = patch_producer(meta)
        patch = patch.reshape(patch.shape[0], -1)
        outputs = net(inputs, patch)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()
        if not cosine:
            scheduler.step()
        train_loss += loss.item()
        _, predicted = outputs.max(1)
        all_preds.extend(predicted.cpu().tolist())
        all_targets.extend(targets.cpu().tolist())

        progress_bar(epoch, max_epochs, batch_idx, len(trainloader), 'Loss: %.3f   Acc: %.3f%%'
                     % (train_loss/(batch_idx+1), 100.*balanced_accuracy_score(all_targets, all_preds)))
    if cosine:
        scheduler.step()


def test(epoch, max_epochs, net, patch_producer, testloader, criterion, device):
    net.eval()
    test_loss = 0
    all_preds = []
    all_targets = []
    with torch.no_grad():
        for batch_idx, (inputs, targets, meta) in enumerate(testloader):
            inputs, targets, meta = inputs.to(device), targets.to(device), meta.to(device)
            patch = patch_producer(meta)
            inputs[:, :, :16, 16:] = patch
            outputs = net(inputs)
            loss = criterion(outputs, targets)

            test_loss += loss.item()
            _, predicted = outputs.max(1)
            all_preds.extend(predicted.cpu().tolist())
            all_targets.extend(targets.cpu().tolist())

            progress_bar(epoch, max_epochs, batch_idx, len(testloader), 'Loss: %.3f   Acc: %.3f%%'
                         % (test_loss/(batch_idx+1), 100.*balanced_accuracy_score(all_targets, all_preds)))
    return 100.*balanced_accuracy_score(all_targets, all_preds)

def fit_model(model, patch_producer, trainloader, testloader, device, epochs:int, learning_rate:float, max_lr:float, momentum:float, save_path:str, bias=0.1, cosine=False):
    best_acc = -1
    best_name = ""
    
    # weight = torch.tensor([bias, 1.0]).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.SGD(model.parameters(), lr=learning_rate, momentum=momentum, weight_decay=5e-4)
    if not cosine:
        scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr, epochs=epochs, steps_per_epoch=len(trainloader))
    else:
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs)
    
    for epoch in range(epochs):
        train(epoch, epochs, model, patch_producer, trainloader, optimizer, scheduler, criterion, device)
        acc = test(epoch, epochs, model, patch_producer, testloader, criterion, device)
        if acc > best_acc:
            if best_name != "":
                os.remove(best_name)
            best_acc = acc
            best_name = save_path + "_" + str(epoch) + ".pth"
            torch.save(model.state_dict(), best_name)
    f = open(save_path + "_best.txt", "w")
    f.write(str(best_acc))
    f.close()
    return best_name, best_acc


def main(dataset:str, model_name:str, epochs:int, learning_rate:float, batch_size:int, max_lr:float, momentum:float, output_prefix:str, cosine:bool):
    print("CUDA Available: ", torch.cuda.is_available())
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    trainloader, testloader, bias = get_dataset(batch_size, individual=True, return_meta=True, tile=True)    
    model = get_model(model_name)
    model = vit_b_16_faster(intermediate_embedding_size=768)
    model.to(device)
    patch_producer = PatchProducer(36, 16, 0.2)
    model.to(device)
    patch_producer.to(device)
    os.makedirs("trained_models/" + model_name +"/", exist_ok=True)
    best_name, best_accuracy = fit_model(model, patch_producer, trainloader, testloader, device, epochs, learning_rate, max_lr, momentum, "trained_models/" + model_name + "/" + output_prefix + dataset + "_" + model_name, bias, cosine)
    print("Training complete: " + best_name + " with accuracy: " + str(round(best_accuracy, 4)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Train a model on a dataset')
    parser.add_argument('--dataset', type=str, default='mammograms', help='Dataset to train on')
    parser.add_argument('--model', type=str, default='vit', help='Model to train')
    parser.add_argument('--output_prefix', type=str, default='', help='Prefix to add to model name, to avoid overlapping experiments.')
    parser.add_argument('--epochs', type=int, default=120, help='Number of epochs to train')
    parser.add_argument('--learning_rate', type=float, default=3e-4, help='Learning rate')
    parser.add_argument('--max_lr', type=float, default=0.1, help='Learning rate')
    parser.add_argument('--batch_size', type=int, default=16, help='Batch size')
    parser.add_argument('--momentum', type=float, default=0.4, help='SGD Momentum')
    parser.add_argument('--cosine', type=bool, default=True, help='Use Cosine Annealing')
    args = parser.parse_args()
    main(args.dataset, args.model, args.epochs, args.learning_rate, args.batch_size, args.max_lr, args.momentum, args.output_prefix, args.cosine)