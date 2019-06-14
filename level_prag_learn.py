import random
import numpy as np
from math import log, log1p, exp
from scipy.special import logsumexp, softmax
from copy import deepcopy
from argparse import ArgumentParser
import pickle

import utilities
import hypotheses
from plot_graph import plot_graph

def sample(posterior):
    """ Pick an index in a list, with probability proportional to its designated probability """
    return np.random.choice(np.arange(len(posterior)), p=np.exp(posterior))


def calc_mental_state(perspective, context):
    """ Given speaker's perspective and the context,
    compute a probability distribution over the referents
    of how likely the speaker is to speak about each referent
    p. 88 Equation 3.1 """
    distribution = np.zeros(len(context))
    for o in range(len(context)):
        distribution[o] = log(1 - abs(perspective - context[o]))
    return utilities.normalize_logprobs(distribution)


def list1_lit_spkr(signal, meaning, language, ref_distribution):
    """ The perspective-taking listener uses Bayes rule to compute the
    probability of a certain referent being intended by the speaker given the 
    produced signal, a language, and the listener's model of the speaker's 
    distribution over referents given their perspective """
    # get the list of signals which can be used for the given meaning
    signals_for_r = signals[np.where(language[meaning] != '0')]
    num_signals_for_r = len(signals_for_r)
    # compute the product of the probability that the speaker chooses referent r and that signal s is produced 
    if signal in signals_for_r:
        if num_signals_for_r == len(signals):
            in_language = log(1 / num_signals_for_r)
        else:
            in_language = log((1 - noise) / num_signals_for_r)
        return ref_distribution[meaning] + in_language
    else:
        out_of_language = log(noise / (len(signals) - num_signals_for_r))
        return ref_distribution[meaning] + out_of_language


def list1_perception_matrix(language, ref_distribution):
    """ Turn the level-1 listener's model of the literal 
        speaker into a perception matrix """
    mat = np.zeros((len(signals), len(meanings)))
    for s in range(len(signals)):
        row = np.zeros(len(meanings))
        for m in meanings:
            row[m] = list1_lit_spkr(signals[s], m, language, ref_distribution)
        mat[s] = utilities.normalize_logprobs(row)
    return mat


def list2_spkr1(signal, meaning, language, ref_distribution):
    """ The level-2 pragmatic listener """
    s_index = np.where(signals == signal)
    # compute the probability of the speaker producing the signal, with noise
    speaker_probs = spkr1_production_probs(meaning, language, ref_distribution)
    noisy_speaker_probs = deepcopy(speaker_probs)
    for s in range(len(noisy_speaker_probs)):
        noisy_speaker_probs[s] = noisy_speaker_probs[s] + log(1 - noise)
        other_signals = [noisy_speaker_probs[os] for os in range(len(noisy_speaker_probs)) if os != s]
        noisy_speaker_probs[s] = logsumexp([noisy_speaker_probs[s], (log(noise) + logsumexp(other_signals)) - log(len(signals) - 1)])

    return ref_distribution[meaning] + noisy_speaker_probs[s_index]


def update_posterior(posterior, signal, context):
    """ Update the posterior probabilities the learner has assigned to
    each lexicon/perspective pair based on the observed signal
    and context """
    new_posterior = np.zeros(len(posterior))
    for i in range(len(posterior)): # for each hypothesis
        language = hypotheses[i][0]
        perspective = hypotheses[i][1]
        pragmatic_lvl = hypotheses[i][2]

        ref_distribution = calc_mental_state(perspective, context)

        marginalize = np.zeros(len(meanings))
        if pragmatic_lvl == 0:
            for m in meanings:
                marginalize[m] = list1_lit_spkr(signal, m, language, ref_distribution) # level-1 listener
        elif pragmatic_lvl == 1:
            for m in meanings:
                marginalize[m] = list2_spkr1(signal, m, language, ref_distribution) # level-2 listener

        new_posterior[i] = posterior[i] + logsumexp(marginalize)
    return utilities.normalize_logprobs(new_posterior)


def spkr1_production_probs(meaning, language, mental_state):
    """ The level-1 pragmatic speaker computes the utility of producing each signal
    based on the the probability that the level-1 listener will understand the intended meaning
    of that signal """
    # compute the utility of each signal as the negative surprisal of the intended
    # referent given the signal, for the listener
    signal_utility = np.array([alpha*list1_perception_matrix(language, mental_state)[s][meaning] for s in range(len(signals))])
    
    # use softmax to get distribution over signals
    return np.log(softmax(signal_utility))


def produce(system, context):
    """ Speaker produces a signal """
    language = system[0]
    perspective = system[1]
    pragmatic_lvl = system[2]
    mental_state = calc_mental_state(perspective, context)
    meaning = sample(mental_state)
    
    """ Production is done differently depending on if the speaker is pragmatic or not """
    if pragmatic_lvl == 0:
        signal = signals[utilities.wta(language[meaning])]

        signals_for_r = [signals[s] for s in range(len(meanings)) if language[meaning][s] == '1']
        num_signals_for_r = len(signals_for_r)
        # with small probability (noise), pick a signal that doesn't correspond to
        # the selected meaning in the given language
        if random.random() < noise and num_signals_for_r != 3:
            other_signals = deepcopy(signals)
            for s in signals_for_r:
                other_signals = signals[np.where(signals != s)]
            signal = np.random.choice(other_signals)
    elif pragmatic_lvl == 1:
        # choose the best signal given the pragmatically-derived probability distribution
        signal = signals[np.random.choice(np.arange(len(signals)), p=np.exp(spkr1_production_probs(meaning, language, mental_state)))]
        
        # with small probability (noise), pick a different signal
        if random.random() < noise:
            other_signals = deepcopy(signals)
            other_signals = signals[np.where(signals != signal)]
            signal = np.random.choice(other_signals) 
    return [signal, context]


def simulation(speaker, no_productions, priors, hypoth_index, contexts):
    posteriors = deepcopy(priors)
    # posterior_list = [exp(posteriors[hypoth_index])]
    posterior_list = [np.exp(posteriors)]
    for i in range(no_productions):
        d = produce(speaker, contexts[i])
        posteriors = update_posterior(posteriors, d[0], d[1])
        # posterior_list.append(exp(posteriors[hypoth_index]))
        posterior_list.append(np.exp(posteriors))
    return np.swapaxes(np.array(posterior_list), 0, 1)


def main():
    parser = ArgumentParser()
    parser.add_argument("o", type=str, help="prefix for the output files")
    parser.add_argument("p", type=int, help="use pragmatic speakers", default="0")
    args = parser.parse_args()
    filename = args.o

    # lexicon where each meaning is associated with its corresponding signal
    # lexicon where the last meaning is associated with all signals
    # lexicon where only one signal is used for every meaning
    # non-pragmatic speakers
    literal_speakers = [188, 182, 171] 
    # pragmatic speakers
    prag_speakers = [874, 868, 857]    

    # Generate maximally informative contexts, which are all possible permutations of
    # [0.1, 0.2, 0.9] and [0.1, 0.8, 0.9] (12 in total)
    contexts = []
    for _ in range(25):
        for c in [[0.1, 0.2, 0.9], [0.1, 0.8, 0.9]]:
            contexts.append([c[0], c[1], c[2]])
            contexts.append([c[1], c[0], c[2]])
            contexts.append([c[1], c[2], c[0]])
            contexts.append([c[2], c[1], c[0]])
            contexts.append([c[2], c[0], c[1]])
            contexts.append([c[0], c[2], c[1]])
    contexts = np.array(contexts)

    if args.p == 0:
        speakers = literal_speakers
        not_speakers = prag_speakers
        plotnames = ["Learning the literal speaker (correct)", "Learning the pragmatic speaker (incorrect)"]
    elif args.p == 1:
        speakers = prag_speakers
        not_speakers = literal_speakers
        plotnames = ["Learning the pragmatic speaker (correct)", "Learning the literal speaker (incorrect)"]

    runs = np.zeros((len(speakers), num_runs, num_productions + 1))
    runs_incorrect = np.zeros((len(speakers), num_runs, num_productions + 1))

    for i in range(num_runs):
        for j in range(len(speakers)):
            post_list = simulation(hypotheses[speakers[j]], num_productions, priors, speakers[j], contexts)
            runs[j][i] = post_list[speakers[j]]
            runs_incorrect[j][i] = post_list[not_speakers[j]]

            with open(filename + str(args.p) + '_spkr' + str(j+1) + '_run' + str(i) +'.pickle', 'wb') as f:
                pickle.dump(runs[j][i], f)

    data = np.array(runs)
    data_incorrect = np.array(runs_incorrect)
    with open(filename + str(args.p) + '_correct.pickle', 'wb') as f:
        pickle.dump(data, f)
    with open(filename + str(args.p) + '_incorrect.pickle', 'wb') as f:
        pickle.dump(data_incorrect, f)

    # Plot the graph for the correct pragmatic level hypothesis and the incorrect one
    plot_graph("p_lvl" + str(args.p), plotnames[0], data)
    plot_graph("p_lvl" + str(args.p) + '_incorrect', plotnames[1], data_incorrect)


if __name__ == "__main__":  
    # Parameters
    noise = 0.05
    perspectives = [0, 1]
    pragmatic_levels = [0, 1]
    meanings = [0, 1, 2]
    signals = np.array(['a', 'b', 'c'])
    p_learner = 1
    alpha = 3.0
    num_productions = 300
    num_runs = 10

    hypotheses, priors = hypotheses.generate_hypotheses(perspectives, p_learner, "egocentric", pragmatic_levels)
    main()