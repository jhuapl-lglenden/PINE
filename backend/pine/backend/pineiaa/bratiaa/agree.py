# Copyright (c) 2019 Tobias Kolditz
# Modifications (C) 2019 The Johns Hopkins University Applied Physics Laboratory LLC.

import logging
from itertools import combinations

import matplotlib.pyplot as plt
import numpy as np
from functools import partial
from scipy.special import comb
from tabulate import tabulate

from ..bratiaa.evaluation import *
from ..bratiaa.utils import TokenOverlap

from collections import namedtuple, Counter

Annotation = namedtuple('Annotation', ['type', 'label', 'offsets'])
AnnFile = namedtuple('AnnFile', ['annotator_id', 'annotations'])

# attempted division by zero is expected and unproblematic -> NaN
np.seterr(divide='ignore', invalid='ignore')

LOGGER = logging.getLogger(__name__)

class Document:
    __slots__ = ['ann_files', 'txt', 'doc_id']

    def __init__(self, txt, doc_id):
        self.txt = txt
        self.doc_id = doc_id
        self.ann_files = []


def input_generator(json_list):
    LOGGER.debug(json_list)
    annotators = set()
    documents = []
    #expects keys text and annotators
    #annotations: {annotator, [[label or start, stop, label]]}
    for id, ann_doc in enumerate(json_list):
        anns_people = []
        #Annotation = namedtuple('Annotation', ['type', 'label', 'offsets'])
        doc = Document(ann_doc['text'], ann_doc['_id'])
        for ann_name, ann_list in ann_doc['annotations'].items():
            anns = []
            for ann in ann_list:
                if len(ann)!=3:
                    continue
                #Evaluation requires a tuple of a tuple of start,stop 
                anns.append(Annotation('T', ann[2], tuple([(ann[0], ann[1])])))
            doc.ann_files.append(AnnFile(ann_name, anns))
            annotators.add(ann_name)
        documents.append(doc)
    return sorted(list(annotators)), documents

def compute_f1(tp, fp, fn):
    return (2 * tp) / (2 * tp + fp + fn)


class F1Agreement:
    def __init__(self, annotators, documents, labels, eval_func=exact_match_instance_evaluation, token_func=None):
        assert len(annotators) > 1, 'At least two annotators are necessary to compute agreement!'
        num_pairs = comb(len(annotators), 2, exact=True)
        # (p, d, c, l) where p := annotator pairs, d := documents, c := counts (tp, fp, fn), l := labels
        self._pdcl = np.zeros((num_pairs, len(documents), 3, len(labels)))
        self._documents = list(documents)
        self._doc2idx = {d: i for i, d in enumerate(documents)}
        self._labels = list(labels)
        self._label2idx = {l: i for i, l in enumerate(labels)}
        self._annotators = list(annotators)
        self._pairs = [pair for pair in combinations(annotators, 2)]
        self._pair2idx = {p: i for i, p in enumerate(self._pairs)}
        # add pairs in reverse order (same index)
        for (a1, a2), value in self._pair2idx.copy().items():
            self._pair2idx[(a2, a1)] = value
        self._eval_func = eval_func  # function used to extract true positives, false positives and false negatives
        self._token_func = token_func  # function used for tokenization
        self._compute_tp_fp_fn(documents)

    @property
    def annotators(self):
        return list(self._annotators)

    @property
    def documents(self):
        return list(self._documents)

    @property
    def labels(self):
        return list(self._labels)

    def _compute_tp_fp_fn(self, documents):
        for doc_index, document in enumerate(documents):
            assert doc_index < len(self._documents), 'Input generator yields more documents than expected!'
            to = None
            if self._token_func:
                text = document.txt
                tokens = list(self._token_func(text))
                to = TokenOverlap(text, tokens)
            for anno_file_1, anno_file_2 in combinations(document.ann_files, 2):
                tp, fp, fn = self._eval_func(anno_file_1.annotations, anno_file_2.annotations, tokens=to)
                pair_idx = self._pair2idx[(anno_file_1.annotator_id, anno_file_2.annotator_id)]
                doc_idx = self._doc2idx[document]
                self._increment_counts(tp, pair_idx, doc_idx, 0)
                self._increment_counts(fp, pair_idx, doc_idx, 1)
                self._increment_counts(fn, pair_idx, doc_idx, 2)

    def _increment_counts(self, annotations, pair, doc, kind):
        for a in annotations:
            try:
                self._pdcl[pair][doc][kind][self._label2idx[a.label]] += 1
            except KeyError:
                logging.error(
                    f'Encountered unknown label "{a.label}"! Please make sure that your "annotation.conf" '
                    f'(https://brat.nlplab.org/configuration.html#annotation-configuration) '
                    f'is located under the project root and contains an exhaustive list of entities!'
                )
                raise

    def mean_sd_per_label(self):
        """
        Mean and standard deviation of all annotator combinations' F1 scores by label.
        """
        pcl = np.sum(self._pdcl, axis=1)  # sum over documents
        f1_pairs = compute_f1(pcl[:, 0], pcl[:, 1], pcl[:, 2])
        avg, stddev = self._mean_sd(f1_pairs)
        return avg, stddev

    def mean_sd_per_document(self):
        """
        Mean and standard deviation of all annotator combinations' F1 scores per document.
        """
        pdc = np.sum(self._pdcl, axis=3)  # sum over labels
        f1_pairs = compute_f1(pdc[:, :, 0], pdc[:, :, 1], pdc[:, :, 2])
        avg, stddev = self._mean_sd(f1_pairs)
        return avg, stddev

    def mean_sd_total(self):
        """
        Mean and standard deviation of all annotator cominations' F1 scores.
        """
        pc = np.sum(self._pdcl, axis=(1, 3))  # sum over documents and labels
        f1_pairs = compute_f1(pc[:, 0], pc[:, 1], pc[:, 2])
        avg, stddev = self._mean_sd(f1_pairs)
        return avg, stddev

    def mean_sd_per_label_one_vs_rest(self, annotator):
        """
        Mean and standard deviation of all annotator combinations' F1 scores involving given annotator per label.
        """
        pcl = np.sum(self._pdcl, axis=1)  # sum over documents
        pcl = pcl[self._pairs_involving(annotator)]
        f1_pairs = compute_f1(pcl[:, 0], pcl[:, 1], pcl[:, 2])
        avg, stddev = self._mean_sd(f1_pairs)
        return avg, stddev

    def mean_sd_total_one_vs_rest(self, annotator):
        """
        Mean and standard deviation of all annotator combinations' F1 scores involving given annotator.
        """
        pc = np.sum(self._pdcl, axis=(1, 3))  # sum over documents and labels
        pc = pc[self._pairs_involving(annotator)]
        f1_pairs = compute_f1(pc[:, 0], pc[:, 1], pc[:, 2])
        if len(f1_pairs) > 1:
            avg, stddev = self._mean_sd(f1_pairs)
        else:
            avg, stddev = f1_pairs, 0
        return avg, stddev

    def _pairs_involving(self, annotator):
        return [self._pair2idx[(a1, a2)] for (a1, a2) in self._pairs if
                a1 == annotator or a2 == annotator]

    @staticmethod
    def _mean_sd(f1_pairs):
        """
        Mean and standard deviation along first axis.
        """
        f1 = np.mean(f1_pairs, axis=0)
        f1_std = np.std(f1_pairs, axis=0)
        return f1, f1_std

    @staticmethod
    def print_table(row_label_header, row_labels, avg, stddev, precision=3):
        stats = np.stack((row_labels, avg, stddev)).transpose()
        headers = [row_label_header, 'Mean F1', 'SD F1']
        LOGGER.debug(tabulate(stats, headers=headers, tablefmt='github', floatfmt=f'.{precision}f'))

    def compute_total_f1_matrix(self):
        """
        Returns (n x n) matrix, where n is the number of annotators, containing
        pair-wise total F1 scores between all annotators.

        By definition, the matrix is symmetric and F1 = 1 on the main diagonal.
        """
        pc = np.sum(self._pdcl, axis=(1, 3))  # sum over documents and labels
        f1_pairs = compute_f1(pc[:, 0], pc[:, 1], pc[:, 2])
        num_annotators = len(self._annotators)
        f1_matrix = np.zeros((num_annotators, num_annotators))
        annotator2idx = {a: i for i, a in enumerate(self._annotators)}
        for ann1, ann2 in self._pairs:
            ann1_idx, ann2_idx = annotator2idx[ann1], annotator2idx[ann2]
            f1_matrix[ann1_idx][ann2_idx] = f1_pairs[self._pair2idx[(ann1, ann2)]]
            f1_matrix[ann2_idx][ann1_idx] = f1_pairs[self._pair2idx[(ann2, ann1)]]
        # perfect diagonal by definition
        for i in range(len(self._annotators)):
            f1_matrix[i][i] = 1
        return f1_matrix

    def draw_heatmap(self, out_path):
        """
        Draws heatmap based on square matrix of F1 scores.
        """
        matrix = self.compute_total_f1_matrix()
        fig, ax = plt.subplots()
        im = ax.imshow(matrix)
        # ticks and labels
        num_annotators = len(self._annotators)
        ax.set_xticks(np.arange(num_annotators))
        ax.set_yticks(np.arange(num_annotators))
        # show complete grid
        ax.set_ylim(-0.5, num_annotators - 0.5)
        ax.set_ylim(num_annotators - 0.5, -0.5)
        ax.set_xticklabels(self._annotators)
        ax.set_yticklabels(self._annotators)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right",
                 rotation_mode="anchor")
        for i in range(len(self._annotators)):
            for j in range(len(self._annotators)):
                ax.text(j, i, f'{matrix[i, j]:.2f}', ha="center", va="center", color="w")

        # color bar
        cbar = ax.figure.colorbar(im, ax=ax)
        cbar.ax.set_ylabel('F1 score', rotation=-90, va="bottom")

        fig.tight_layout()
        plt.savefig(out_path)


def compute_f1_agreement(annotators, documents, labels, token_func=None, eval_func=None):
    if not eval_func:
        eval_func = exact_match_instance_evaluation
        if token_func:
            eval_func = exact_match_token_evaluation

    #input_gen = partial(input_gen, project_root)
    #annotators, documents = _collect_annotators_and_documents(input_gen)

    return F1Agreement(annotators, documents, sorted(labels), eval_func=eval_func, token_func=token_func)


def iaa_report(f1_agreement, precision=3):
    agreement_type = '* Instance-based F1 agreement'
    if f1_agreement._token_func:
        agreement_type = '* Token-based F1 agreement'

    LOGGER.debug(f'# Inter-Annotator Agreement Report\n')

    LOGGER.debug(agreement_type)

    LOGGER.debug('\n## Project Setup\n')
    LOGGER.debug(f'* {len(f1_agreement.annotators)} annotators: {", ".join(f1_agreement.annotators)}')
    LOGGER.debug(f'* {len(f1_agreement.documents)} agreement documents')
    LOGGER.debug(f'* {len(f1_agreement.labels)} labels')

    docids = [d.doc_id for d in f1_agreement.documents]
    LOGGER.debug('\n## Agreement per Document\n')
    #f1_agreement.print_table('Document', f1_agreement.documents, *f1_agreement.mean_sd_per_document(), precision=precision)
    f1_agreement.print_table('Document', docids, *f1_agreement.mean_sd_per_document(), precision=precision)

    LOGGER.debug('\n## Agreement per Label\n')
    f1_agreement.print_table('Label', f1_agreement.labels, *f1_agreement.mean_sd_per_label(), precision=precision)

    LOGGER.debug('\n## Overall Agreement\n')
    avg, stddev = f1_agreement.mean_sd_total()
    LOGGER.debug(f'* Mean F1: {avg:.{precision}f}, SD F1: {stddev:.{precision}f}\n')
