import random
import matplotlib.pyplot as plt
plt.switch_backend('agg')

from math import log, log1p, exp
from scipy.special import logsumexp, softmax
from numpy import argmax

from copy import deepcopy

import utilities

""" Parameters """
noise = 0.05
perspectives = [0, 1]
num_signals = 3
meanings = [0, 1, 2]
signals = ['a', 'b', 'c']
p_learner = 1
alpha = 3.0
# num_signals = 2
# meanings= [0, 1]
# signals = ['a', 'b']
# languages = [[[1, 1], [1, 1]], [[1, 1], [1, 0]], [[1, 1], [0, 1]], [[1, 0], [1, 1]], [[1, 0], [1, 0]], [[1, 0], [0, 1]], [[0, 1], [1, 1]], [[0, 1], [1, 0]], [[0, 1], [0, 1]]]

""" Generate 3x3 lexicon matrices, only if every meaning has at least one signal """
languages = []
for i in range(pow(2, 9), 0, -1):
    string = str(format(i, 'b'))
    if len(string) >= 7: # eliminate strings that don't have a signal for meaning 0
        while len(string) < 9:
            string = '0' + string # pad with 0s
        # eliminate strings that don't have a signal for meanings 1 and 2
        if string[-3:] != '000' and string[3:-3] != '000':
            # create matrix
            languages.append([[string[0],string[1],string[2]],
                [string[3],string[4],string[5]],
                [string[6],string[7],string[8]]])

# generate list of language-perspective pairs and generate priors
lp_pairs = []
priors_unbiased = []
priors_egocentric = []
for p in perspectives:
    for l in languages:
        lp_pairs.append([l, p])
        priors_unbiased.append(log(1/len(perspectives)) + log(1/len(languages)))

        p_prior = log(0.9) if p == p_learner else log(0.1)
        priors_egocentric.append(p_prior + log(1/len(languages)))

""" Pick a meaning with probability proportional to its designated probability """
def sample(posterior):
    return meanings[utilities.log_roulette_wheel(posterior)]

""" Given speaker's perspective and the context,
    compute a probability distribution over the referents
    of how likely the speaker is to speak about each referent
    p. 88 Equation 3.1 """
def calc_mental_state(perspective, context):
    distribution = []
    for o in context:
        distribution.append(log(1 - abs(perspective - o)))
    return utilities.normalize_logprobs(distribution)

""" The perspective-taking listener uses Bayes rule to compute the
    probability of a certain referent being intended by the speaker given the 
    produced signal, a language, and the listener's model of the speaker's 
    distribution over referents given their perspective """
def list1_lit_spkr(signal, meaning, language, ref_distribution):
    # get the list of signals which can be used for the given meaning
    signals_for_r = [signals[s] for s in range(len(meanings)) if language[meaning][s] == '1']
    num_signals_for_r = len(signals_for_r)
    # compute the product of the probability that the speaker chooses referent r and that signal s is produced 
    if signal in signals_for_r:
        if num_signals_for_r == num_signals:
            in_language = log(1 / num_signals_for_r)
        else:
            in_language = log((1 - noise) / num_signals_for_r)
        return ref_distribution[meaning] + in_language
    else:
        out_of_language = log(noise / (num_signals - num_signals_for_r))
        return ref_distribution[meaning] + out_of_language

def list1_perception_matrix(language, ref_distribution):
    mat = []
    for s in signals:
        row = []
        for m in meanings:
            row.append(list1_lit_spkr(s, m, language, ref_distribution))
        mat.append(utilities.normalize_logprobs(row))
    return mat

""" The level-2 pragmatic listener """
# TODO: fix the way the likelihood is computed
def list2_spkr1(signal, meaning, language, ref_distribution):
    # get the list of signals which can be used for the given meaning
    s_index = signals.index(signal)

    # compute the probability of the speaker producing the signal, with noise
    speaker_probs = spkr1_production_probs(meaning, language, ref_distribution)
    noisy_speaker_probs = deepcopy(speaker_probs)
    for s in range(len(noisy_speaker_probs)):
        noisy_speaker_probs[s] = noisy_speaker_probs[s] + log(1 - noise)
        other_signals = [noisy_speaker_probs[os] for os in range(len(noisy_speaker_probs)) if os != s]
        noisy_speaker_probs[s] = logsumexp([noisy_speaker_probs[s], (log(noise) + logsumexp(other_signals)) - log(len(signals) - 1)])
    # print(exp(noisy_speaker_probs[s_index]))
    return ref_distribution[meaning] + noisy_speaker_probs[s_index]

""" Update the posterior probabilities the learner has assigned to
    each lexicon/perspective pair based on the observed signal
    and context """
def update_posterior(posterior, signal, context):
    new_posterior = []
    for i in range(len(posterior)): # for each hypothesis
        language = lp_pairs[i][0]
        perspective = lp_pairs[i][1]

        ref_distribution = calc_mental_state(perspective, context)

        marginalize = []
        for meaning in meanings:
            marginalize.append(list2_spkr1(signal, meaning, language, ref_distribution))
            # marginalize.append(list1_lit_spkr(signal, meaning, language, ref_distribution)) # level-1 listener
        
        new_posterior.append(posterior[i] + logsumexp(marginalize))
    return utilities.normalize_logprobs(new_posterior)

""" The level-1 pragmatic speaker computes the probability of producing each signal
    given the intended meaning, their language, and their mental state
    (a distrubtion over meanings given their perspective and the context) """
def spkr1_production_probs(meaning, language, mental_state):
    # compute the utility of each signal as the negative surprisal of the intended
    # referent given the signal, for the listener
    signal_utility = [alpha*list1_perception_matrix(language, mental_state)[s][meaning] for s in range(len(signals))]
    
    # use softmax to get distribution over signals
    return [log(p) for p in softmax(signal_utility)]

""" Speaker produces a signal """
def produce(system, context):
    language = system[0]
    perspective = system[1]
    mental_state = calc_mental_state(perspective, context)
    meaning = sample(mental_state)
    
    # choose the best signal given the pragmatically-derived probability distribution
    signal = signals[utilities.log_roulette_wheel(spkr1_production_probs(meaning, language, mental_state))]

    # with small probability (noise), pick a different signal
    if random.random() < noise:
        other_signals = deepcopy(signals)
        other_signals.remove(signal)
        signal = random.choice(other_signals) 
    return [signal, context]

def plot_graph(results_list):
    colors = ['darkseagreen', 'steelblue', 'mediumpurple']
    labels = ['Most informative', 'Medium informative', 'Least informative']
    
    for i in range(len(results_list)):
        average = []
        for result in results_list[i]:
            plt.plot(result, color=colors[i], alpha=0.3)

        for j in range(len(results_list[i][0])):
            total = 0
            for result in results_list[i]:
                total += result[j]
            average.append(total / len(results_list[i]))

        plt.plot(average, color=colors[i], label=labels[i])
    plt.xlabel('data points seen')
    plt.ylabel('posterior')
    plt.legend()
    plt.grid()
    plt.savefig('prag_combined_plot_test.png')

def simulation(speaker, no_productions, priors, hypoth_index, contexts):
    posteriors = deepcopy(priors)
    posterior_list = [exp(posteriors[hypoth_index])]
    for i in range(no_productions):
        d = produce(speaker, contexts[i])
        posteriors = update_posterior(posteriors, d[0], d[1])
        posterior_list.append(exp(posteriors[hypoth_index]))
    return posterior_list

speaker1 = lp_pairs[188] # lexicon where each meaning is associated with its corresponding signal
# speaker2 = lp_pairs[0] # lexicon where every signal is used for every meaning
speaker3 = lp_pairs[171] # lexicon where only one signal is used for every meaning
speaker2 = lp_pairs[182] # lexicon where the last meaning is associated with all signals

#[0.1, 0.2, 0.9]  and [0.1, 0.8, 0.9]
contexts = []
for i in range(25):
    for c in [[0.1, 0.2, 0.9], [0.1, 0.8, 0.9]]:
        contexts.append([c[0], c[1], c[2]])
        contexts.append([c[1], c[0], c[2]])
        contexts.append([c[1], c[2], c[0]])
        contexts.append([c[2], c[1], c[0]])
        contexts.append([c[2], c[0], c[1]])
        contexts.append([c[0], c[2], c[1]])
# contexts = [[random.random(), random.random(), random.random()] for i in range(500)]

runs1 = []
runs2 = []
runs3 = []

for i in range(10):
    post_list1 = simulation(speaker1, 300, priors_egocentric, 188, contexts)
    runs1.append(post_list1)
    post_list2 = simulation(speaker2, 300, priors_egocentric, 182, contexts)
    runs2.append(post_list2)
    post_list3 = simulation(speaker3, 300, priors_egocentric, 171, contexts)
    runs3.append(post_list3)
all_runs = [runs1, runs2, runs3]
# # all_runs = [runs2]
plot_graph(all_runs)


## DEBUGGING ##
# speaker_test = lp_pairs[497] # lexicon where the last meaning is associated with all signals
# d = produce(speaker_test, [0.1, 0.2, 0.9])
# print([exp(p) for p in calc_mental_state(speaker_test[1], [0.1, 0.2, 0.9])])
# for m in meanings:
#     spkr1_production_probs(m, speaker_test[0], calc_mental_state(speaker_test[1], [0.1, 0.2, 0.9]))
# update_posterior(priors_egocentric, d[0], d[1])
# for m in meanings:
#     for s in signals:
#         list1_lit_spkr(s, m, speaker_test[0], calc_mental_state(speaker_test[1], [0.1, 0.2, 0.9]))
        # list2_spkr1(s, m, speaker_test[0], calc_mental_state(speaker_test[1], [0.1, 0.2, 0.9]))