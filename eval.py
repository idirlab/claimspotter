import tensorflow as tf
from keras.preprocessing.sequence import pad_sequences
import numpy as np
import math
import os
from utils.data_loader import DataLoader
from sklearn.metrics import f1_score, classification_report
from flags import FLAGS

x = tf.placeholder(tf.int32, (None, FLAGS.max_len), name='x')
y = tf.placeholder(tf.int32, (None, FLAGS.num_classes), name='y')
kp_emb = tf.placeholder(tf.float32, name='kp_emb')
kp_lstm = tf.placeholder(tf.float32, name='kp_lstm')
cls_weight = tf.placeholder(tf.float32, (None,), name='cls_weight')

computed_cls_weights = []
pad_index = -1


def pad_seq(inp):
    global pad_index

    if pad_index == -1:
        pad_index = len(DataLoader.get_default_vocab()) - 1

    return pad_sequences(inp, padding="pre", maxlen=FLAGS.max_len, value=pad_index)


def one_hot(a):
    return np.squeeze(np.eye(FLAGS.num_classes)[np.array(a).reshape(-1)])


def get_cls_weights(batch_y):
    return [computed_cls_weights[z] for z in batch_y]


def eval_stats(sess, batch_x, batch_y, cost, acc, y_pred):
    if len(batch_x) == 0 and len(batch_y) == 0:
        return 0.0, 0.0, 0.0
    eval_loss = sess.run(
        cost,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )
    eval_acc = sess.run(
        acc,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )
    preds = sess.run(
        y_pred,
        feed_dict={
            x: pad_seq(batch_x),
            y: one_hot(batch_y),
            kp_emb: 1.0,
            kp_lstm: 1.0,
            cls_weight: get_cls_weights(batch_y)
        }
    )

    return np.sum(eval_loss), eval_acc, np.argmax(preds, axis=1)


def load_model(sess, graph):
    global x, y, kp_emb, kp_lstm, cls_weight

    def get_last_save(scan_loc):
        ret_ar = []
        directory = os.fsencode(scan_loc)
        for fstr in os.listdir(directory):
            if '.meta' in os.fsdecode(fstr) and 'cb.ckpt-' in os.fsdecode(fstr):
                ret_ar.append(os.fsdecode(fstr))
        ret_ar.sort()
        return ret_ar[-1]

    model_dir = os.path.join(FLAGS.output_dir, get_last_save(FLAGS.output_dir))
    tf.logging.info('Attempting to restore from {}'.format(model_dir))

    with graph.as_default():
        saver = tf.train.import_meta_graph(model_dir)
        saver.restore(sess, tf.train.latest_checkpoint(FLAGS.output_dir))

        # inputs
        x = graph.get_tensor_by_name('x:0')
        y = graph.get_tensor_by_name('y:0')
        kp_emb = graph.get_tensor_by_name('kp_emb:0')
        kp_lstm = graph.get_tensor_by_name('kp_lstm:0')
        cls_weight = graph.get_tensor_by_name('cls_weight:0')

        # outputs
        cost = graph.get_tensor_by_name('cost:0')
        y_pred = graph.get_tensor_by_name('y_pred:0')
        acc = graph.get_tensor_by_name('acc:0')

        tf.logging.info('Model successfully restored.')
        return cost, y_pred, acc


def get_batch(bid, data):
    batch_x = []
    batch_y = []

    for i in range(FLAGS.batch_size):
        idx = bid * FLAGS.batch_size + i
        if idx >= (FLAGS.total_examples if FLAGS.disjoint_data else FLAGS.test_examples):
            break
        batch_x.append(data.x[idx])
        batch_y.append(data.y[idx])

    return batch_x, batch_y


def main():
    global computed_cls_weights

    os.environ['CUDA_VISIBLE_DEVICES'] = ','.join([str(z) for z in FLAGS.gpu_active])

    tf.logging.info("Loading dataset")
    data_load = DataLoader(FLAGS.custom_prc_data_loc, FLAGS.custom_vocab_loc, ver='eval') if FLAGS.disjoint_data else \
        DataLoader(ver='eval')
    computed_cls_weights = data_load.class_weights

    test_data = data_load.load_all_data() if FLAGS.disjoint_data else data_load.load_testing_data()
    tf.logging.info("{} testing examples".format(test_data.get_length()))

    graph = tf.Graph()
    with tf.Session(graph=graph, config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        sess.run(tf.global_variables_initializer())
        cost, y_pred, acc = load_model(sess, graph)

        n_batches = math.ceil(
            float(FLAGS.total_examples if FLAGS.disjoint_data else FLAGS.test_examples) / float(FLAGS.batch_size))

        n_samples = 0
        eval_loss = 0.0
        eval_acc = 0.0

        y_all = []
        pred_all = []

        for i in range(n_batches):
            batch_x, batch_y = get_batch(i, test_data)

            b_loss, b_acc, b_pred = eval_stats(sess, batch_x, batch_y, cost, acc, y_pred)
            if b_loss == 0 and b_acc == 0 and b_pred == 0:
                continue

            eval_loss += b_loss
            eval_acc += b_acc * len(batch_y)
            n_samples += len(batch_y)

            y_all = np.concatenate((y_all, batch_y))
            pred_all = np.concatenate((pred_all, b_pred))

        f1score = f1_score(y_all, pred_all, average='weighted')

        eval_loss /= n_samples
        eval_acc /= n_samples

        print('Labels:', y_all)
        print('Predic:', pred_all)

        tf.logging.info('Final stats | Loss: {:>7.4} Acc: {:>7.4f}% F1: {:>.4f}'.format(
            eval_loss, eval_acc * 100, f1score))

        target_names = (['NFS', 'UFS', 'CFS'] if FLAGS.num_classes == 3 else ['NFS/UFS', 'CFS'])
        print(classification_report(y_all, pred_all, target_names=target_names))


if __name__ == '__main__':
    tf.logging.set_verbosity(tf.logging.INFO)
    main()
