import math
import time
import os
from tqdm import tqdm
from shutil import rmtree
from core.utils.data_loader import DataLoader
from core.utils.flags import FLAGS, print_flags
from absl import logging
import tensorflow as tf
import numpy as np
from core.models.model import ClaimSpotterModel

K = tf.keras


def main():
    os.environ['CUDA_VISIBLE_DEVICES'] = ','.join([str(z) for z in FLAGS.cs_gpu])
    os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'

    print_flags()

    if os.path.isdir(FLAGS.cs_tb_dir):
        rmtree(FLAGS.cs_tb_dir)
    if os.path.isdir(FLAGS.cs_model_dir) and not FLAGS.cs_restore_and_continue:
        print('Continue? (y/n) You will overwrite the contents of FLAGS.cs_model_dir ({})'.format(FLAGS.cs_model_dir))
        inp = input().strip('\r\n\t')
        if inp.lower() == 'y':
            rmtree(FLAGS.cs_model_dir)
        else:
            print('Exiting...')
            exit()
    if not os.path.isdir(FLAGS.cs_model_dir) and FLAGS.cs_restore_and_continue:
        raise Exception('Cannot restore from non-existent folder: {}'.format(FLAGS.cs_model_dir))

    logging.info("Loading dataset")
    data_load = DataLoader()

    train_data = data_load.load_training_data()
    test_data = data_load.load_testing_data()

    logging.info("{} training examples".format(train_data.get_length()))
    logging.info("{} validation examples".format(test_data.get_length()))

    dataset_train = tf.data.Dataset.from_tensor_slices(([x[0] for x in train_data.x], [x[1] for x in train_data.x], train_data.y)).shuffle(
        buffer_size=train_data.get_length()).batch(FLAGS.cs_batch_size_reg if not FLAGS.cs_adv_train else FLAGS.cs_batch_size_adv)
    dataset_test = tf.data.Dataset.from_tensor_slices(([x[0] for x in test_data.x], [x[1] for x in test_data.x], test_data.y)).shuffle(
        buffer_size=test_data.get_length()).batch(FLAGS.cs_batch_size_reg if not FLAGS.cs_adv_train else FLAGS.cs_batch_size_adv)

    logging.info("Warming up...")

    model = ClaimSpotterModel(cls_weights=data_load.class_weights)
    model.warm_up()

    start_epoch, end_epoch = 0, FLAGS.cs_train_steps

    if FLAGS.cs_restore_and_continue:
        logging.info('Attempting to restore weights from {}'.format(FLAGS.cs_model_dir))

        last_epoch = model.load_custom_model()

        start_epoch += last_epoch + 1
        end_epoch += last_epoch + 1 + FLAGS.cs_train_steps

        logging.info('Restore successful')

    logging.info("Starting{}training...".format(' ' if not FLAGS.cs_adv_train else ' adversarial '))

    epochs_trav = 0
    for epoch in range(start_epoch, end_epoch, 1):
        epochs_trav += 1
        epoch_loss, epoch_acc = 0, 0
        start = time.time()

        pbar = tqdm(total=math.ceil(
            len(train_data.y) / (FLAGS.cs_batch_size_reg if not FLAGS.cs_adv_train else FLAGS.cs_batch_size_adv)))
        for x_id, x_sent, y in dataset_train:
            x = (x_id, x_sent)
            train_batch_loss, train_batch_acc = (model.train_on_batch(x, y) if not FLAGS.cs_adv_train
                                                 else model.adv_train_on_batch(x, y))
            epoch_loss += train_batch_loss
            epoch_acc += train_batch_acc * np.shape(y)[0]
            pbar.update(1)
        pbar.close()

        epoch_loss /= train_data.get_length()
        epoch_acc /= train_data.get_length()

        if epoch % FLAGS.cs_stat_print_interval == 0:
            log_string = 'Epoch {:>3} Loss: {:>7.4} Acc: {:>7.4f}% '.format(epoch + 1, epoch_loss, epoch_acc * 100)

            if test_data.get_length() > 0:
                val_loss, val_acc = 0, 0

                for x_id, x_sent, y in dataset_test:
                    x = (x_id, x_sent)
                    val_batch_loss, val_batch_acc = model.stats_on_batch(x, y)
                    val_loss += val_batch_loss
                    val_acc += val_batch_acc * np.shape(y)[0]

                val_loss /= test_data.get_length()
                val_acc /= test_data.get_length()

                log_string += 'Dev Loss: {:>7.4f} Dev Acc: {:>7.4f} '.format(val_loss, val_acc)

            log_string += '({:3.3f} sec/epoch)'.format((time.time() - start) / epochs_trav)

            logging.info(log_string)

            start = time.time()
            epochs_trav = 0

        if epoch % FLAGS.cs_model_save_interval == 0:
            model.save_custom_model(epoch)


if __name__ == '__main__':
    logging.set_verbosity(logging.INFO)
    main()
