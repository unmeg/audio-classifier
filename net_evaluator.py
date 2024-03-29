import numpy as np

import torch
import torch.nn as nn
import torch.optim as optim
import torch.utils.data as data

from torch.autograd import Variable

from tensorboardX import SummaryWriter

import librosa, time, os, datetime, glob

class NetEvaluator(object):
    """Trains and Tests a Neural Net

    Attributes:
        net (:class:`torch.nn.Module`): Network to use
        dataset (:class: `np.array`): The dataset to train/test on
        test_percent (float, optional): How much of the given dataset to use as testing
        learning_rate (float, optional)
        starting_epoch (int, optional)
        num_epochs (int, optional)
        checkpoint_every_epochs (int, optional): Creates a checkpoint every X epochs. Set to higher than `num_epochs` for no checkpoints.
        test_threshold (float, optional)
        checkpoint_label (string, optional)
        mfcc (bool, optional): Evaluate dataset as mfcc
        n_mels (int, optional)
        n_fft (int, optional)
        hop_length (int, optional)
        window (string, optional)
        fmin (int, optional)
        fmax (int, optional)
        batch_size (int, optional)
        optimizer (:obj:`torch.optim`, optional)
        loss_function (:obj: `torch.nn._Loss`, optional)
    """
    def __init__(self,
        net,
        dataset,
        test_percent=0.15,
        learning_rate=1e-4,
        starting_epoch=0,
        num_epochs=100,
        checkpoint_every_epochs=5,
        test_threshold=0.25,
        checkpoint_label='raw_large_f64',
        mfcc=False,
        n_mels = 80,
        n_fft = 512,
        hop_length = 160, # 0.010 x 16000
        window = 'hann',
        fmin = 125,
        fmax = 7600,
        batch_size = 256,
        optimizer=None,
        loss_function=None
    ):

        self.net = net
        self.dataset = dataset
        self.test_percent = test_percent
        self.learning_rate = learning_rate

        self.starting_epoch = starting_epoch
        self.num_epochs = num_epochs
        self.test_threshold = test_threshold

        self.batch_size = 512
        self.generate_dataloaders()

        self.optimizer = optimizer or optim.Adam(params=self.net.parameters(), lr=self.learning_rate)
        self.loss_function = loss_function or nn.CrossEntropyLoss()

        self.dtype = torch.FloatTensor
        self.num_gpus = torch.cuda.device_count()

        # Check how many GPUs, do cuda/DataParallel accordingly
        if self.num_gpus > 0:
            self.dtype = torch.cuda.FloatTensor
            self.net.cuda()

        if self.num_gpus > 1:
            self.net = nn.DataParallel(self.net).cuda()

        self.mfcc = mfcc
        self.n_mels = n_mels
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.window = window
        self.fmin = fmin
        self.fmax = fmax

        self.checkpoint_every_epochs = checkpoint_every_epochs
        self.loss_log = []
        self.checkpoint_dir = '/home/mining-test/dataset/checkpoints_raw_large_f64/'
        self.checkpoint_label = checkpoint_label
        self.load_checkpoint()

        self.tensorboard = True
        self.plot = 0
        self.val_plot = 0
        self.init_writer()


    def generate_dataloaders(self):
        """Generate the train and test dataloaders."""
        rand_idxs = torch.randperm(len(self.dataset))
        test_size = int(np.floor(len(self.dataset) * self.test_percent))

        test_idxs = rand_idxs[:test_size]
        train_idxs = rand_idxs[test_size:]

        self.train_dl = data.DataLoader(
            self.dataset,
            sampler=data.sampler.SubsetRandomSampler(train_idxs),
            batch_size=self.batch_size,
            num_workers=0
        )

        self.test_dl = data.DataLoader(
            self.dataset,
            sampler=data.sampler.SubsetRandomSampler(test_idxs),
            batch_size=self.batch_size,
            num_workers=0
        )

    def load_checkpoint(self):
        """Attempt to load the latest saved learning checkpoint."""
        # Create a checkpoint directory if none exists
        if not os.path.exists(self.checkpoint_dir):
            os.makedirs(self.checkpoint_dir)
            print("\nCreated a 'checkpoints' folder to save/load the model")

        # Find the highest epoch number in the checkpoint_dir (or 0)
        checkpoint_epoch = max([int(x.split('_')[-1].split('.')[0]) for x in glob.glob(self.checkpoint_dir + '*')] + [0])

        try:
            # load the checkpoint
            filename = '{:s}checkpoint_{:s}_epoch_{:06d}.pt'.format(self.checkpoint_dir, self.checkpoint_label, checkpoint_epoch)
            checkpoint = torch.load(filename)

            # set the model state
            self.net.load_state_dict(checkpoint['state_dict'])

            # set optimizer state
            self.optimizer = optim.Adam(params=self.net.parameters(), lr=self.learning_rate)
            self.optimizer.load_state_dict(checkpoint['optimizer'])
            self.starting_epoch = checkpoint['epoch']
            self.loss_log = checkpoint['loss_log']

            print("\nLoaded checkpoint: " + filename)
        except FileNotFoundError:
            print("\nNo checkpoint found, starting training")


    def init_writer(self):
        """Init the TensorboardX `SummaryWriter`."""
        tensor_label = 'tb_{}_{}'.format(self.checkpoint_label, datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))

        if not os.path.exists("logs/"+ tensor_label):
            os.makedirs("logs/" + tensor_label)

        self.writer = SummaryWriter('./logs/' + tensor_label)

    def prepareMfcc(self, x):
        """Prepare a section of the dataset to be evaluated as mfcc."""
        # pre-computed power spec
        s = np.abs(librosa.core.stft(y=x, n_fft=self.n_fft, hop_length=self.hop_length, window=self.window, center=True))
        # passed to melfilters
        spectro = librosa.feature.melspectrogram(S=s, n_mels=self.n_mels, fmax=self.fmax, fmin=self.fmin, power=2, n_fft=self.n_fft, hop_length=self.hop_length)
        #logamplitude
        x_hold = librosa.core.amplitude_to_db(S=spectro, ref=1.0, amin=5e-4, top_db=80.0)
        return x_hold


    def train(self):
        """Train the Network on the dataset."""
        # turn on training mode
        self.net.train()

        for x, y in self.train_dl:

            if self.mfcc:
                x_raw = x.clone()
                x = torch.empty((x_raw.shape[0], 1, 80, 52), dtype=x_raw.dtype)
                for mfcc_i in range(x_raw.shape[0]):
                    x_mfcc = self.prepareMfcc(x_raw[mfcc_i, 0, :].numpy())
                    x[mfcc_i, 0, :, :] = torch.from_numpy(x_mfcc)

            # Set the vars to use cuda if available
            if self.num_gpus > 0:
                x_var = x.cuda(non_blocking=True)
                y_var = y.cuda(non_blocking=True).type(torch.cuda.LongTensor)

            # Regular Tensors if not
            else:
                x_var = Variable(x).type(torch.FloatTensor)
                y_var = Variable(y).type(torch.LongTensor)


            # Forward pass
            out = self.net(x_var)

            # Compute loss
            loss = self.loss_function(out, y_var)
            self.loss_log.append(loss.item())

            # Zero gradients before the backward pass
            self.optimizer.zero_grad()

            # Backprop
            loss.backward()

            # Update the params
            self.optimizer.step()

            if self.tensorboard:
                self.writer.add_scalar('train/loss', loss.item(), self.plot)
                self.plot += 1

        return loss.item()

    def test(self):
        """Run tests and predictions on the test dataloader."""
        self.net.eval() # eval mode

        correct = 0
        total = 0

        for x, y in self.train_dl:

            if self.mfcc:
                x_raw = x.clone()
                x = torch.empty((x_raw.shape[0], 1, 80, 52), dtype=x_raw.dtype)
                for mfcc_i in range(x.shape[0]):
                    x_mfcc = self.prepareMfcc(x_raw[mfcc_i, 0, :].numpy())
                    x[mfcc_i, 0, :, :] = torch.from_numpy(x_mfcc)

            # Set x to use cuda if available
            if self.num_gpus > 0:
                x_var = x.cuda(non_blocking=True)
            else:
                x_var = Variable(x.type(torch.FloatTensor))

            # y has to be a non-cuda LongTensor
            y = y.type(torch.LongTensor)

            # Run x_var through the network and extract the predictions
            outputs = self.net(x_var)
            _, predicted = torch.max(outputs.data, 1)

            total += y.size(0)
            # Because it's a 0-5 floating scale, allow a small leeway for being correct enough
            correct += (abs(predicted.cpu() - y) <= self.test_threshold).sum()

        accuracy = 100 * correct / total
        return accuracy

    def eval(self):
        """Run both train and test on the dataset `self.num_epochs` times."""
        best_epoch = 0
        best_accuracy = 0
        best_loss = 0

        start_time = time.time()

        for epoch in range(self.starting_epoch, self.num_epochs):
            try:
                loss = self.train()
                print('Epoch {}/{} training loss: {:.2f}'.format(epoch, self.num_epochs, loss))
                accuracy = self.test()
                print('Epoch {}/{} validation accuracy: {:.2f}%'.format(epoch, self.num_epochs, accuracy))

                if self.tensorboard:
                    self.writer.add_scalar('val/accuracy', accuracy, self.val_plot)
                    self.val_plot += 1

                if loss > best_loss:
                    loss = best_loss

                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_epoch = epoch
                    # Save the net state when we get a new best
                    torch.save(self.net.state_dict(), 'best_model.pkl')

                # Save a checkpoint every `self.checkpoint_every_epochs` epochs
                if (epoch % self.checkpoint_every_epochs == 0 or epoch == (self.num_epochs-1)) and (epoch != self.starting_epoch):
                    save_file = '{:s}checkpoint_{:s}_epoch_{:06d}.pt'.format(self.checkpoint_dir, self.checkpoint_label, epoch)
                    save_state = {
                        'epoch': epoch,
                        'state_dict': self.net.state_dict(),
                        'optimizer' : self.optimizer.state_dict(),
                        'best_loss' : best_loss,
                        # 'bad_epoch' : scheduler.num_bad_epochs,
                        'loss_log' : self.loss_log
                    }
                    torch.save(save_state, save_file)
                    print('\nCheckpoint saved')

            except KeyboardInterrupt: # Allow loop breakage
                print('\nBest accuracy of {}% at epoch {}\n'.format(best_accuracy, best_epoch))
                break

        time_taken = time.time() - start_time
        print('\nBest accuracy of {}% at epoch {}/{} in {} seconds'.format(best_accuracy, best_epoch, self.num_epochs, time_taken))
