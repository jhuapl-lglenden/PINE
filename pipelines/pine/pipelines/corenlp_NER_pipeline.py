#!/usr/bin/env python3
# coding: utf8
# (C) 2019 The Johns Hopkins University Applied Physics Laboratory LLC.

import logging
import os
from os.path import isfile, isdir, join
import textwrap
import uuid

from .pipeline import Pipeline
from .shared.config import ConfigBuilder

config = ConfigBuilder.get_config()
logger = logging.getLogger(__name__)

#also imports pyjnius after configuring java environment variables
#NOTE: jvm will run out of memory if you train too many times while it is running, cause of leak unknown
#in the meantime if you must call fit a lot, destroy the object and create a new one to reset the jvm

class corenlp_NER(Pipeline):
    #Path variables
    __jar = ''
    __jdk_dir = ''

    #files output in the process of training model
    #id is so the output files are unique to each instantiation, otherwise weird things will happen if we decide to use query-by-committee
    #TODO: maybe don't use id if it isn't specified?
    __train_file = ''
    __test_file = '' #TODO: only really needed for evaluate_orig, maybe remove?
    __model = ''
    __temp_dir = None

    #model variables
    __crf = None
    __props = None

    #class variables
    __id = None

    #init()
    #set tunable parameters
    #TODO: Should probably make this more robust by inserting try/catch
    def __init__(self, java_dir=None, ner_path=None, load_model=None, tmp_dir=None):

        self.__id = uuid.uuid4()

        if tmp_dir != None:
            self.__temp_dir = tmp_dir
            #can choose to dictate where the model will store files so that it doesn't overwrite any,
            #otherwise it will write to a new directory within the resources folder
        else:
            self.__temp_dir = config.ROOT_DIR + '/tmp/' + str(self.__id)

        if not isdir(self.__temp_dir):
            os.makedirs(self.__temp_dir)
        logger.info("Using temp dir {}".format(self.__temp_dir))

        self.__train_file = join(self.__temp_dir, 'corenlp_training.tsv')
        self.__test_file = join(self.__temp_dir, 'corenlp_test_gold.tsv')
        self.__model = join(self.__temp_dir, 'corenlp-ner-model.ser.gz')


        #TODO: set defaults for the following.
        #Point to location of JAVA installation
        if java_dir != None:
            self.__jdk_dir = java_dir
        else:
            self.__jdk_dir = '/usr/lib/jvm/java-1.8.0-openjdk-amd64' # self.__jdk_dir = '/usr/lib/jvm/java-8-oracle'
        if isdir(self.__jdk_dir):
            os.environ['JAVA_HOME'] = self.__jdk_dir
        else:
            raise ImportError("ERROR: JAVA installation not found")


        #Point to Location of Stanford NER Library
        if ner_path != None:
            self.__jar = ner_path
        else:
            self.__jar = './resources/stanford-corenlp-full-2018-02-27/stanford-corenlp-3.9.1.jar'
        if isfile(self.__jar):
            os.environ['CLASSPATH'] = self.__jar
        else:
            raise ImportError("ERROR: Stanford NER Library not found")

        #if you get to this point, java and stanford ner library should be located
        import jnius_config
        if not jnius_config.vm_running:
            print('Configured JVM')
            jnius_config.add_options('-Xmx32g') #allocate enough memory to the JVM heap to run the classifier
        else:
            raise RuntimeWarning('WARNING: JVM already running. Cannot run core nlp')

        #import pyjnius to import required classes from JAVA/Stanford NER
        from jnius import autoclass

        #General
        self.__java_String = autoclass("java.lang.String")

        #TOKENIZING
        self.__java_StringReader = autoclass("java.io.StringReader")
        self.__java_Tokenizer = autoclass("edu.stanford.nlp.process.PTBTokenizer")

        #TRAINING AND TESTING CRFCLASSIFIER
        self.__java_CRFClassifier = autoclass("edu.stanford.nlp.ie.crf.CRFClassifier")
        self.__java_Properties = autoclass("java.util.Properties")
        self.__java_AA = autoclass("edu.stanford.nlp.ling.CoreAnnotations$AnswerAnnotation")

        #GETTING CONFIDENCES
        self.__java_CRFCliqueTree = autoclass("edu.stanford.nlp.ie.crf.CRFCliqueTree")

        if load_model != None:
            self.__crf = self.__java_CRFClassifier.getClassifier(self.__java_String(load_model))
            self.__model = load_model

        self.__SCNLP = autoclass("edu.stanford.nlp.pipeline.StanfordCoreNLP")


    #fit(X, y)
    #internal state is changed
    def fit(self, X, y, params=None):

        default_params = {
            'import_prop_file': None,
            'export_prop_file': None,
            'max_left': 1,
            'use_class_feature': True,
            'use_word': True,
            'use_ngrams': True,
            'no_mid_ngrams': True,
            'max_ngram_length': 6,
            'use_prev': True,
            'use_next': True,
            'use_disjunctive': True,
            'use_sequences': True,
            'use_prev_sequences': True,
            'use_type_seqs': True,
            'use_type_seqs2': True,
            'use_type_y_sequences': True,
            'word_shape': "chris2useLC"
        }
        #format input data into tsv file for ner to train on
        try:
            train_data = self.format_data(X, y)
            if len(train_data) == 0 or train_data is None:
                raise Exception("ERROR: could not format input correctly")
        except:
            raise Exception("ERROR: could not format input correctly")

        with open(self.__train_file, 'w') as f:
            for doc in train_data:
                for ent in doc:
                    f.write(ent[0] + '\t' + ent[1]  + '\n')
                f.write('\n')
        if params is not None:
            for key in default_params.keys():
                if key in params:
                    default_params[key] = params[key]
        #if user wants to use their own properties load it, otherwise we make our own
        if default_params["import_prop_file"] != None and isfile(default_params["import_prop_file"]):
            with open(default_params["import_prop_file"], 'r') as f:
                prop_text = f.read()
        else:
            prop_text = textwrap.dedent(
    """# location of the training file
trainFile = """+ self.__train_file + """
# location where you would like to save (serialize) your
# classifier; adding .gz at the end automatically gzips the file,
# making it smaller, and faster to load
serializeTo = """ + self.__model + """

# structure of your training file; this tells the classifier that
# the word is in column 0 and the correct answer is in column 1
map = word=0,answer=1

# This specifies the order of the CRF: order 1 means that features
# apply at most to a class pair of previous class and current class
# or current class and next class.
maxLeft=""" + str(default_params["max_left"]) + """

# these are the features we'd like to train with
useClassFeature=""" + str(default_params["use_class_feature"]) + """
useWord=""" + str(default_params["use_word"]) + """
useNGrams=""" + str(default_params["use_ngrams"]) + """
noMidNGrams=""" + str(default_params["no_mid_ngrams"]) + """
maxNGramLeng=""" + str(default_params["max_ngram_length"]) + """
usePrev=""" + str(default_params["use_prev"]) + """
useNext=""" + str(default_params["use_next"]) + """
useDisjunctive=""" + str(default_params["use_disjunctive"]) + """
useSequences=""" + str(default_params["use_sequences"]) + """
usePrevSequences=""" + str(default_params["use_prev_sequences"]) + """
# the last 4 properties deal with word shape features
useTypeSeqs=""" + str(default_params["use_type_seqs"]) + """
useTypeSeqs2=""" + str(default_params["use_type_seqs2"]) + """
useTypeySequences=""" + str(default_params["use_type_y_sequences"]) + """
wordShape=""" + default_params["word_shape"] + """
""")
        #user can choose to export the properties file they used if they wish
        if default_params["export_prop_file"] != None:
            with open(default_params["export_prop_file"], 'w') as f:
                f.write(prop_text)

        #load properties into the model and train
        p = self.__java_StringReader(self.__java_String(prop_text))
        self.__props = self.__java_Properties()
        self.__props.load(p)

        if self.__crf != None:
            self.__SCNLP.clearAnnotatorPool()
            del self.__crf #may clear up some memory, unclear how much of an effect it has

        self.__crf = self.__java_CRFClassifier(self.__props)

        self.__crf.train()

        #TODO: make this user optional? or just have them call save_model?
        modelPath = self.__props.getProperty(self.__java_String("serializeTo"))
        self.__crf.serializeClassifier(self.__java_String(modelPath))
        os.remove(self.__train_file)



    #predict(X, Xid)
    #returns {text_id: [[offset_start, offset_end, label], ... []], ...}
    def predict(self, X, Xid):
        out = {}
        for doc, doc_id in zip(X, Xid):
            doc_ents = []
            test_text = self.__java_String(doc)
            results = self.__crf.classify(test_text)

            for s in range(results.size()):
                for w in range(results.get(s).size()):
                    word = results.get(s).get(w)
                    start_char = word.beginPosition()
                    end_char = word.endPosition()
                    label = word.get(self.__java_AA)
                    #print(str(start_char) + '-' + str(end_char) + ': ' + word.word() + '/' + label)
                    if label != 'O':
                        doc_ents.append((start_char, end_char, label))
            out[doc_id] = doc_ents
        return out

    #predict_proba(X, Xid)
    #returns {text_id: [(offset_start, offset_end, label, score), ... []], ...}
    #can also return scores for all labels if get_all is True
    def predict_proba(self, X, Xid, get_all_labels=False, include_other=False):
        out = {}
        # Score is confidence of classifier for this prediction
        for doc, doc_id in zip(X, Xid):
            doc_ents = []
            test_text = self.__java_String(doc)
            results = self.__crf.classify(test_text)

            for s in range(results.size()):
                cliqueTree = self.__crf.getCliqueTree(results.get(s))
                for w in range(cliqueTree.length()):
                    word = results.get(s).get(w)
                    start_char = word.beginPosition()
                    end_char = word.endPosition()
                    label = word.get(self.__java_AA)
                    #to capture data for tokens marked 'O' set include_other to True, else these will not be included in the calculations
                    if (include_other == True) or (label != 'O' and include_other == False):
                        if get_all_labels == False:
                            index = self.__crf.classIndex.indexOf(self.__java_String(label))
                            prob = cliqueTree.prob(w, index)
                            #print(str(start_char) + '-' + str(end_char) + ': ' + word.word() + '/' + label)
                            doc_ents.append((start_char, end_char, label, prob))
                        else:
                            itr = self.__crf.classIndex.iterator()
                            all_probs = []
                            while itr.hasNext():
                                label = itr.next()
                                index = self.__crf.classIndex.indexOf(self.__java_String(label))
                                prob = cliqueTree.prob(w, index)
                                all_probs.append((label, prob))
                            doc_ents.append((start_char, end_char, all_probs))

            out[doc_id] = doc_ents
        return out


    #TODO: next_example(X, Xid)
    #Given model's current state evaluate the input (id, String) pairs and return a rank ordering of lowest->highest scores for instances (will need to discuss specifics of ranking)
    #Discussing rank is now a major project - see notes
    def next_example(self, X, Xid):
        return

## EXTRA METHODS TO HELP WITH THE corenlp PIPELINE ##
    def get_id(self):
        return self.__id

    #Takes input data and formats it to be easier to use in the corenlp pipeline
    #ASSUMES DATA FOLLOWS FORMAT X = [string], y = [[(start offset, stop offset, label), ()], ... []]
    #Currently cannot assign more than one label to the same word
    def format_data(self, X, y):
        out = []
        for doc,ann in zip(X,y):
            #Extract labeled entities from doc
            doc_ents = []
            cursor = 0
            #puts labeled entities in order within each document for next part
            ann.sort(key=lambda tup: tup[0])
            for ent in ann:
                label = ent[2]
                start_char = ent[0]
                end_char = ent[1]
                ent_text = doc[start_char:end_char]
                #if there is text before the token, insert it
                if cursor < start_char:
                    doc_ents.append((doc[cursor:start_char], 'O'))
                #this is to prevent tokens from being added more than once (TODO: may want to experiment with other ways of handling multiple labels)
                if cursor <= start_char:
                    doc_ents.append((ent_text, label))
                if cursor <= end_char:
                    cursor = end_char
            if doc[cursor:] != '': #don't want to add a blank accidentally
                doc_ents.append((doc[cursor:], 'O'))
            #print(doc_ents)

            ent_extract = []
            for text, l in doc_ents:
                words = self.tokenize(str(text))
                #print(words)
                #there were several cases where there would be no words (only spaces),
                #the if mitigates that error
                if words:
                    for w in words:
                        ent_extract.append((w,l))
            out.append(ent_extract)
        return out

    #saves model so that it can be loaded again later
    #models must be saved with extension ".ser.gz"
    def save_model(self, model_name):
        if not model_name.endswith(".ser.gz"):
            print('WARNING: model_name must end in .ser.gz, adding...')
            model_name = model_name + ".ser.gz"
        self.__crf.serializeClassifier(self.__java_String(model_name))
        print('Saved model to ' + model_name)
        return model_name


    #loads a previously saved model
    #properties can be exported/imported during train
    def load_model(self, model_name):
        #TODO: what to do if model doesn't exist?
        if not model_name.endswith(".ser.gz"):
            print('WARNING: model_name must end in .ser.gz, adding...')
            model_name = model_name + ".ser.gz"
        self.__crf = self.__java_CRFClassifier.getClassifier(self.__java_String(model_name))
        self.__model = model_name

    #method for tokenizing text
    #TODO: currently this implementation of corenlp doesn't support more than one label per token
    def tokenize(self, input_text):
        #print(input_text)
        text = self.__java_String(input_text)

        r = self.__java_StringReader(text)
        t = self.__java_Tokenizer.newPTBTokenizer(r)

        tokens = []

        while t.hasNext():
            w = t.next()
            tokens.append(w.word())

        return tokens

    #Calculates Precision, Recall, and F1 Score for model based on input test data
    #WARNING: currently works for BioNLP data, no guarantees with other datasets
    def evaluate(self, X, y, Xid, verbose=False):

        known_labels = set()
        for anns in y:
            for ann in anns:
                known_labels.add(ann[2])

        stats = {}

        try:
            train_data = self.format_data(X, y)
            if len(train_data) == 0 or train_data is None:
                raise Exception("ERROR: could not format input correctly")
        except:
            raise Exception("ERROR: could not format input correctly")
        test_text = ''

        for doc in X:
            test_text = test_text + doc + '\n\n'
        #rest of code tries to recreate calculations as this line, which can't be called more than once for some reason
        #results = self.__crf.classifyAndWriteAnswers(self.__java_String(self.__test_file), True)
        #print(test_text)
        results = self.__crf.classify(self.__java_String(test_text))


        #Calculate evaluation by iterating through answer key and matching tokens to classifier output
        s = 0
        w = 0
        prev_gold = ''
        prev_guess = ''
        next_guess = None

        for d, doc in enumerate(train_data):
            for i, answer in enumerate(doc):
                #Find corresponding token in gold and predicted
                word = answer[0]
                gold = answer[1]
                if verbose: print('GOLD: ' + word + ',' + gold)

                if word == '<xn>':
                    if verbose: print('SKIP')
                    continue

                if next_guess != None:
                    guess = next_guess
                else:
                    guess = (results.get(s).get(w).word(), results.get(s).get(w).get(self.__java_AA))

                a = 1
                votes = {guess[1]: 1}
                next_guess = None
                #if the tokens don't match, loop until they do
                while word != guess[0]:

                    if len(word) > len(guess[0]) and word[0:len(guess[0])] == guess[0]: #if the classifier has tokenized more finely than the answer, then keep adding the next tokens to the guessed token until it matches
                        #since tokens sometime have to be concatenated, we use a voting system,
                        #where the most popular label of all of the individual tokens is used
                        to_add = (results.get(s).get(w+a).word(), results.get(s).get(w+a).get(self.__java_AA))
                        if to_add[1] not in votes:
                            votes[to_add[1]] = 1
                        votes[to_add[1]] += 1
                        #use the most popular label based on the individual tokens
                        guess = (guess[0] + to_add[0], sorted(votes, key=votes.__getitem__, reverse=True)[0])
                        a = a + 1
                    elif len(word) < len(guess[0]) and word == guess[0][0:len(word)]: #if the guessed token is larger than the answer, break the rest off into the next guess
                        next_guess = (guess[0][len(word):], guess[1])
                        guess = (guess[0][0:len(word)], guess[1])
                    else: #if the guess token does not match any part of the answer token, then move on to the next token without adding
                        w = w + 1
                        if w >= results.get(s).size():
                            w = 0
                            s = s + 1
                        if s >= results.size():
                            break
                        guess = (results.get(s).get(w).word(), results.get(s).get(w).get(self.__java_AA))
                        next_guess = None
                        a = 1
                        votes = {guess[1]: 1} #reset votes when concatenation is discarded
                    if verbose: print(guess)

                    #check what the next gold token is, if it matches with the current guess then just move on
                    #(likely the current answer token doesn't exactly match the guess token, see `` vs '')
                    if i+1 < len(doc):
                        next_gold = doc[i+1]
                    elif i >= len(doc) and d+1 < len(test_data):
                        next_gold = test_data[d+1][0]
                    else:
                        next_gold = (None, None)
                    if guess[0] == next_gold[0]: break
                if word != guess[0]: continue

                #if the code gets to here we are pretty confident the tokens match
                if verbose: print('GUESS: ' + str(guess))

                pred = guess[1]

                known_labels.add(pred)

                # Per token metriccs
                for label in known_labels:
                    if label not in stats:
                        stats[label] = [0, 0, 0, 0]




                if gold == pred and gold != 'O':
                    stats[gold][0] = stats[gold][0] + 1
                    for label in known_labels:
                        if label != gold:
                            stats[label][3] = stats[label][3] + 1
                elif gold == 'O' and pred != 'O':
                    stats[pred][1] = stats[pred][1] + 1
                    for label in known_labels:
                        if label != pred:
                            stats[label][3] = stats[label][3] + 1
                elif pred == 'O' and gold != 'O':
                    stats[gold][2] = stats[gold][2] + 1
                    for label in known_labels:
                        if label != gold:
                            stats[label][3] = stats[label][3] + 1
                else:
                    for label in known_labels:
                        stats[label][3] = stats[label][3] + 1


                # Per annotation metrics
                # if gold not in stats:
                #     stats[gold] = [0, 0, 0]
                # if pred not in stats:
                #     stats[pred] = [0, 0, 0]
                # if gold == pred:
                #     #TRUE POSITIVE
                #     #Stanford NLP considers adjacent tokens with the same (non 'O') label to be one instance of that label
                #     if gold != prev_gold or gold == 'O':
                #         stats[gold][0] = stats[gold][0] + 1
                #         if gold != 'O': stats['Totals'][0] = stats['Totals'][0] + votes[gold]
                #     if verbose: print('TRUE POSITIVE')
                # else:
                #     #GOLD ADDS FALSE NEGATIVE
                #     if gold != prev_gold or gold == 'O':
                #         stats[gold][2] = stats[gold][2] + 1
                #         if gold != 'O': stats['Totals'][2] = stats['Totals'][2] + 1
                #     if verbose: print('FALSE NEGATIVE FOR ' + gold)
                #     #pred ADDS FALSE POSITIVE
                #     if pred != prev_guess or pred == 'O':
                #         stats[pred][1] = stats[pred][1] + 1
                #         if pred != 'O': stats['Totals'][1] = stats['Totals'][1] + (votes[pred] if pred in votes else 1)
                #     if verbose: print('FALSE POSITIVE FOR ' + pred)
                #
                # #if tokens had to be concatenated and they were not all the same label
                # if len(votes) > 1:
                #     for label in sorted(votes, key=votes.__getitem__, reverse=True)[1:]:
                #         if label not in stats:
                #             stats[label] = [0, 0, 0]
                #         stats[label][1] += votes[label] #add false positives to all the labels other than the most popular one as well
                #         if verbose: print('FALSE POSITIVE FOR ' + label)
                #
                # prev_gold = gold
                # prev_guess = pred

        #removes stats for 'O' as we don't really care about that;
        #ONLY USED FOR PER ANNOTATION METRICS
        # del stats['O']

        TP = 0
        TN = 0
        FP = 0
        FN = 0
        for key in stats:
            TP = TP + stats[key][0]
            FP = FP + stats[key][1]
            FN = FN + stats[key][2]
            TN = TN + stats[key][3]

        stats['Totals'] = [TP, FP, FN, TN]



        #print(test_data[-1])
        for key in stats:
            TP = stats[key][0]
            FP = stats[key][1]
            FN = stats[key][2]
            # Only generated when using per token metrics
            TN = stats[key][3]
            if (TP+FN) != 0:
                recall = TP/(TP+FN)
            else:
                recall = 1.0
            if (TP+FP) != 0:
                precision = TP/(TP+FP)
            else:
                precision = 0.0
            if (precision + recall) != 0:
                f1 = 2 * (precision * recall) / (precision + recall)
            else:
                f1 = 0
            # Acc Only works when using per token metrics which generates TN
            if (TP + FN + FP + TN) != 0:
                acc = (TP + TN) / (TP + FN + FP + TN)
            else:
                acc = 0
            #Used for annotation metrics
            # stats[key] = {'precision': precision, 'recall': recall, 'f1': f1, 'TP': TP, 'FP': FP, 'FN': FN}
            # Used for token metrics
            stats[key] = {'precision': precision, 'recall': recall, 'f1': f1, 'TP': TP, 'FP': FP, 'FN': FN, 'TN': TN, 'acc': acc}

        return stats

            #Calculates Precision, Recall, and F1 Score for model based on input test data
    #TODO: prints a whole lot to the command line, find a way to suppress?
    def evaluate_orig(self, X, y, Xid):
        try:
            test_data = self.format_data(X, y)
            if len(test_data) == 0 or test_data is None:
                raise Exception("ERROR: could not format input correctly")
        except:
            raise Exception("ERROR: could not format input correctly")

        with open(self.__test_file, 'w') as f:
            for d in test_data:
                for e in d:
                    f.write(e[0] + '\t' + e[1]  + '\n')
                f.write('\n')
        results = self.__crf.classifyAndWriteAnswers(self.__java_String(self.__test_file), True)
        return results


