from data_utils import *
import scipy
############# CONFIG ###########################
database_regex = 'csv/*/record-F*.csv'
suffix = ''

triggering_electrode = 'F7'
electrodes_to_analyze = ['P7','P8','O1','O2']

common_avg_ref = False
ref_electrodes = []

all_electrodes = np.unique([triggering_electrode] + electrodes_to_analyze + ref_electrodes)

# Filtering options
filter_on = True
low_cutoff = 0.5
high_cutoff = 24 # desired cutoff frequency of the filter, Hz (0 to disable filtering)

# Define pre and post stimuli period of chunk (in seconds)
pre_stimuli = time2sample(0.1)
post_stimuli = time2sample(0.5)

# Define threshold for trigger signal
max_trigger_peak_width = time2sample(3) # in seconds
slope_width = 7 # in number of samples, controls shift of the stimuli start

# Valid signal value limits
chunk_max_peak_to_peak = 70
peak_filtering = True
min_peak_score = 2

csvfile = open('amplitudes' + ('_common' if common_avg_ref else '_org') + '.csv', 'w', newline='')
writer = csv.writer(csvfile, delimiter=',', quotechar='|')
writer.writerow(['file', 'electrode', 'amp_angry', 'amp_happy', 'amp_neutral', 'chunks_angry', 'chunks_happy', 'chunks_neutral'])


######### READ SIGNALS FROM DISK ############################

database = read_openvibe_csv_database(database_regex, all_electrodes)


#plot_database(database, 1)


########### SIGNALS FILTERING ###############
from filtering import *

# Modify database by filtering signals
for filename, record in database.items():
    for electrode, signal in record['signals'].items():
        if electrode == triggering_electrode or filter_on:
            # filtered_signal = butter_lowpass_filter(signal, high_cutoff, fs, 6)
            filtered_signal = butter_bandpass_filter(signal, [low_cutoff, high_cutoff], fs)

            database[filename]['signals'][electrode] = filtered_signal
#plot_database(database, 1)

# for filename, record in database.items():
#     for electrode, signal in record['signals'].items():
#         if electrode in electrodes_to_analyze:
#             import numpy as np
#             import matplotlib.pyplot as plt
#             import scipy.fftpack
#
#             N = 4480
#             # sample spacing
#             T = 1.0 / 128.0
#             y = signal[:N]
#             yf = scipy.fftpack.fft(y)
#             xf = np.linspace(0.0, 1.0 / (2.0 * T), N / 2)
#
#             fig, ax = plt.subplots()
#             ax.plot(xf, 2.0 / N * np.abs(yf[:N // 2]))
#             plt.title(electrode)
#             plt.show()


############ CUT THE END OF SIGNAL TO REMOVE FILTERING ARTIFACTS ##################
# Times (in seconds) to cut signals in the beginning and end
left_cut = time2sample(0)
right_cut = time2sample(3)

for filename, record in database.items():
    database[filename]['timestamps'] = record['timestamps'][left_cut:-right_cut]
    for electrode, signal in record['signals'].items():
        database[filename]['signals'][electrode] = signal[left_cut:-right_cut]
#plot_database(database, 1)


########### DISCARD SIGNALS WITHOUT TRIGGER FOUND ###########
trigger_peak_to_peak_min = 500

# Filter by peak-to-peak value
corrupted_files = list()
for filename, record in database.items():
    triggering_signal = record['signals'][triggering_electrode]
    if np.max(triggering_signal) - np.min(triggering_signal) < trigger_peak_to_peak_min:
        print("Cannot find triggering signal in:", filename)
        corrupted_files.append(filename)

if len(corrupted_files) == 0:
    print("No corrupted signals")
else:
    for filename in corrupted_files:
        database.pop(filename, None)

######### EXTRACT CHUNKS OF SIGNAL AFTER STIMULI ##################

def is_face_angry(face_id):
    labels = {1, 4, 7, 10, 13, 16, 20, 22}
    for i in labels:
        if face_id == 33024 + i:
            return True
    return False

def is_face_happy(face_id):
    labels = {3, 5, 8, 12, 14, 18, 21, 23}
    for i in labels:
        if face_id == 33024 + i:
            return True
    return False

def is_face_emotional(face_id):
    if is_face_angry(face_id) or is_face_happy(face_id):
        return True
    return False


def forward_diff(signal, order):
    new_signal = np.zeros_like(signal)
    for n in range(len(signal) - order):
        new_signal[n] = np.sum(np.diff(signal[n:(n + order)]))

    return new_signal

# Init container for ERP chunks
extracted_chunks_angry = OrderedDict()
extracted_chunks_happy = OrderedDict()
extracted_chunks_neutral = OrderedDict()
for e in electrodes_to_analyze:
    extracted_chunks_angry[e] = list()
    extracted_chunks_happy[e] = list()
    extracted_chunks_neutral[e] = list()

for filename, record in database.items():

    # Compute forward difference of triggering electrode signal and find its minima
    raw_trigger_signal = np.array(record['signals'][triggering_electrode])
    trigger_signal = forward_diff(raw_trigger_signal, slope_width)
    trigger_threshold = (np.mean(np.sort(trigger_signal)[:len(record['responses'])]) + np.mean(np.sort(trigger_signal))) / 2

    # #Compare raw triggering signal and its difference
    # plt.figure()
    # plt.plot(range(len(trigger_signal)), raw_trigger_signal, 'b-')
    # #plt.plot(range(len(trigger_signal)), trigger_signal, 'g-', linewidth=1)
    # plt.axhline(trigger_threshold, color='k', linestyle='dashed')
    # plt.xlabel('Time [s]')
    # plt.ylabel('uV')
    # plt.grid()
    # plt.show()

    # Find next stimuli start and save related chunk for every electrode
    i = 0
    trigger_iter = 0
    true_timestamps = list()
    openvibe_timestamps = list()
    while i < len(trigger_signal):
        if trigger_signal[i] < trigger_threshold:

            try:
                was_response_correct = record['responses'][trigger_iter][0]
            except:
                i += 1
                continue

            if was_response_correct:
                # Find stimuli index
                margin = 100
                search_area_start = max(0, i - max_trigger_peak_width // 2)
                search_area_end = min(i + max_trigger_peak_width // 2, len(trigger_signal))
                stimuli_index = int(search_area_start + np.argmin(trigger_signal[search_area_start:search_area_end]))
                if stimuli_index < margin:
                    i += max_trigger_peak_width
                    trigger_iter += 1
                    continue

                #Plot single trigger
                # plt.figure()
                # plt.plot(range(len(trigger_signal[stimuli_index-margin:stimuli_index+margin])), raw_trigger_signal[stimuli_index-margin:stimuli_index+margin], 'g-', linewidth=3)
                # plt.plot(range(len(trigger_signal[stimuli_index-margin:stimuli_index+margin])), trigger_signal[stimuli_index-margin:stimuli_index+margin], 'b-', linewidth=3)
                # plt.axvline(margin, color='k', linestyle='dashed')
                # plt.xlabel('Time [s]')
                # plt.ylabel('uV')
                # #plt.grid()
                # plt.show()

                try:
                    true_timestamps.append(record['timestamps'][stimuli_index])
                    openvibe_timestamps.append(record['order'][trigger_iter][1])
                except:
                    pass

                # Save chunk
                for electrode, signal in record['signals'].items():
                    if electrode in electrodes_to_analyze:
                        if stimuli_index - pre_stimuli < 0 or stimuli_index + post_stimuli > len(signal):
                            continue
                        chunk = signal[stimuli_index - pre_stimuli:stimuli_index + post_stimuli]
                        chunk_max = np.max(chunk)
                        chunk_min = np.min(chunk)
                        chunk_peak_to_peak = chunk_max - chunk_min

                        if peak_filtering:
                            def inv_ric(points, a):
                                return -scipy.signal.ricker(points, a)

                            widths = 0.5 * np.arange(1, 10)
                            cwtmatr = scipy.signal.cwt(chunk, inv_ric, widths)
                            peak_score = np.mean(cwtmatr[:, pre_stimuli + time2sample(0.17)])

                            # plt.figure()
                            # plt.title(peak_score)
                            # plt.imshow(cwtmatr, extent=[-0.2, 1, chunk.min(), chunk.max()], cmap='PRGn', aspect='auto',
                            #            vmax=abs(cwtmatr).max(), vmin=-abs(cwtmatr).max())
                            # plt.show()
                        else:
                            peak_score = min_peak_score + 1

                        if trigger_iter < 0:
                            #Plot triggers
                            plt.figure()
                            plt.title(electrode + (', peak score: ' + str(peak_score)) if peak_filtering else '')
                            plt.plot(((np.array(range(len(chunk)))) - pre_stimuli)/fs, chunk, 'g-', linewidth=1)
                            plt.axvline(0, color='k', linestyle='dashed')
                            plt.axvline(0.17, color='b', linestyle='dashed')
                            plt.xlabel('Time [s]')
                            plt.ylabel('uV')
                            plt.grid()
                            plt.savefig("figures\\" + basename(filename) + "\\chunks\\"+electrode+'_'+str(trigger_iter)+ ('_common' if common_avg_ref else '_org') +'.png')
                            plt.close()

                        if chunk_peak_to_peak < chunk_max_peak_to_peak and peak_score > min_peak_score:
                            try:
                                face_id = record['order'][trigger_iter][0]
                                if len(record['order']) > 0 and is_face_angry(face_id):
                                    extracted_chunks_angry[electrode].append(chunk)
                                elif len(record['order']) > 0 and is_face_happy(face_id):
                                    extracted_chunks_happy[electrode].append(chunk)
                                elif len(record['order']) > 0:
                                    extracted_chunks_neutral[electrode].append(chunk)
                            except:
                                pass

            i += max_trigger_peak_width
            trigger_iter += 1
        else:
            i += 1

    # Calculate difference between true timestamps and openvibe timestamps
    # diff = np.subtract(true_timestamps[:len(openvibe_timestamps)], openvibe_timestamps)
    # m = np.mean(diff)
    # v = np.std(diff)
    print(filename)













common_avg_ref = True
ref_electrodes = ['AF3','F3','FC5','T7','P7','O1','O2','P8','T8','FC6','F4','AF4'] if common_avg_ref else []

all_electrodes = np.unique([triggering_electrode] + electrodes_to_analyze + ref_electrodes)


csvfile = open('amplitudes' + ('_common' if common_avg_ref else '_org') + '.csv', 'w', newline='')
writer = csv.writer(csvfile, delimiter=',', quotechar='|')
writer.writerow(['file', 'electrode', 'amp_angry', 'amp_happy', 'amp_neutral', 'chunks_angry', 'chunks_happy', 'chunks_neutral'])


######### READ SIGNALS FROM DISK ############################

database = read_openvibe_csv_database(database_regex, all_electrodes)

if common_avg_ref:
    ######## COMMON AVERAGE REFERENCE ###########################
    common_database = database.copy()
    for filename, record in database.items():
        for e in electrodes_to_analyze:
            # Find average signal over all ref_electrodes except one being re-referenced
            mean = np.zeros(len(record['signals'][triggering_electrode]))
            count = 0
            for electrode, signal in record['signals'].items():
                if electrode in ref_electrodes and electrode != e:
                    mean += signal
                    count += 1
            mean /= count

            common_database[filename]['signals'][e] -= mean

    database = common_database


#plot_database(database, 1)


########### SIGNALS FILTERING ###############
from filtering import *

# Modify database by filtering signals
for filename, record in database.items():
    for electrode, signal in record['signals'].items():
        if electrode == triggering_electrode or filter_on:
            # filtered_signal = butter_lowpass_filter(signal, high_cutoff, fs, 6)
            filtered_signal = butter_bandpass_filter(signal, [low_cutoff, high_cutoff], fs)

            database[filename]['signals'][electrode] = filtered_signal
#plot_database(database, 1)


############ CUT THE END OF SIGNAL TO REMOVE FILTERING ARTIFACTS ##################
# Times (in seconds) to cut signals in the beginning and end
left_cut = time2sample(0)
right_cut = time2sample(3)

for filename, record in database.items():
    database[filename]['timestamps'] = record['timestamps'][left_cut:-right_cut]
    for electrode, signal in record['signals'].items():
        database[filename]['signals'][electrode] = signal[left_cut:-right_cut]
#plot_database(database, 1)


########### DISCARD SIGNALS WITHOUT TRIGGER FOUND ###########
trigger_peak_to_peak_min = 500

# Filter by peak-to-peak value
corrupted_files = list()
for filename, record in database.items():
    triggering_signal = record['signals'][triggering_electrode]
    if np.max(triggering_signal) - np.min(triggering_signal) < trigger_peak_to_peak_min:
        print("Cannot find triggering signal in:", filename)
        corrupted_files.append(filename)

if len(corrupted_files) == 0:
    print("No corrupted signals")
else:
    for filename in corrupted_files:
        database.pop(filename, None)

######### EXTRACT CHUNKS OF SIGNAL AFTER STIMULI ##################

def is_face_angry(face_id):
    labels = {1, 4, 7, 10, 13, 16, 20, 22}
    for i in labels:
        if face_id == 33024 + i:
            return True
    return False

def is_face_happy(face_id):
    labels = {3, 5, 8, 12, 14, 16, 18, 21}
    for i in labels:
        if face_id == 33024 + i:
            return True
    return False

def is_face_emotional(face_id):
    if is_face_angry(face_id) or is_face_happy(face_id):
        return True
    return False


def forward_diff(signal, order):
    new_signal = np.zeros_like(signal)
    for n in range(len(signal) - order):
        new_signal[n] = np.sum(np.diff(signal[n:(n + order)]))

    return new_signal

# Init container for ERP chunks
extracted_chunks_angry2 = OrderedDict()
extracted_chunks_happy2 = OrderedDict()
extracted_chunks_neutral2 = OrderedDict()
for e in electrodes_to_analyze:
    extracted_chunks_angry2[e] = list()
    extracted_chunks_happy2[e] = list()
    extracted_chunks_neutral2[e] = list()

for filename, record in database.items():

    # Compute forward difference of triggering electrode signal and find its minima
    raw_trigger_signal = np.array(record['signals'][triggering_electrode])
    trigger_signal = forward_diff(raw_trigger_signal, slope_width)
    trigger_threshold = (np.mean(np.sort(trigger_signal)[:len(record['responses'])]) + np.mean(np.sort(trigger_signal))) / 2

    # #Compare raw triggering signal and its difference
    # plt.figure()
    # plt.plot(range(len(trigger_signal)), raw_trigger_signal, 'b-')
    # plt.plot(range(len(trigger_signal)), trigger_signal, 'g-', linewidth=1)
    # plt.axhline(trigger_threshold, color='k', linestyle='dashed')
    # plt.xlabel('Time [s]')
    # plt.ylabel('uV')
    # plt.grid()
    # plt.show()

    # Find next stimuli start and save related chunk for every electrode
    i = 0
    trigger_iter = 0
    true_timestamps = list()
    openvibe_timestamps = list()
    while i < len(trigger_signal):
        if trigger_signal[i] < trigger_threshold:

            try:
                was_response_correct = record['responses'][trigger_iter][0]
            except:
                i += 1
                continue

            if was_response_correct:
                # Find stimuli index
                margin = 100
                search_area_start = max(0, i - max_trigger_peak_width // 2)
                search_area_end = min(i + max_trigger_peak_width // 2, len(trigger_signal))
                stimuli_index = int(search_area_start + np.argmin(trigger_signal[search_area_start:search_area_end]))
                if stimuli_index < margin:
                    i += max_trigger_peak_width
                    trigger_iter += 1
                    continue

                # Plot single trigger
                # plt.figure()
                # plt.plot(range(len(trigger_signal[stimuli_index-margin:stimuli_index+margin])), raw_trigger_signal[stimuli_index-margin:stimuli_index+margin], 'g-', linewidth=3)
                # plt.plot(range(len(trigger_signal[stimuli_index-margin:stimuli_index+margin])), trigger_signal[stimuli_index-margin:stimuli_index+margin], 'b-', linewidth=3)
                # plt.axvline(margin, color='k', linestyle='dashed')
                # plt.xlabel('Time [s]')
                # plt.ylabel('uV')
                # #plt.grid()
                # plt.show()

                try:
                    true_timestamps.append(record['timestamps'][stimuli_index])
                    openvibe_timestamps.append(record['order'][trigger_iter][1])
                except:
                    pass

                # Save chunk
                for electrode, signal in record['signals'].items():
                    if electrode in electrodes_to_analyze:
                        if stimuli_index - pre_stimuli < 0 or stimuli_index + post_stimuli > len(signal):
                            continue
                        chunk = signal[stimuli_index - pre_stimuli:stimuli_index + post_stimuli]
                        chunk_max = np.max(chunk)
                        chunk_min = np.min(chunk)
                        chunk_peak_to_peak = chunk_max - chunk_min

                        if peak_filtering:
                            def inv_ric(points, a):
                                return -scipy.signal.ricker(points, a)

                            widths = 0.5 * np.arange(1, 10)
                            cwtmatr = scipy.signal.cwt(chunk, inv_ric, widths)
                            peak_score = np.mean(cwtmatr[:, pre_stimuli + time2sample(0.17)])

                            # plt.figure()
                            # plt.title(peak_score)
                            # plt.imshow(cwtmatr, extent=[-0.2, 1, chunk.min(), chunk.max()], cmap='PRGn', aspect='auto',
                            #            vmax=abs(cwtmatr).max(), vmin=-abs(cwtmatr).max())
                            # plt.show()
                        else:
                            peak_score = min_peak_score + 1

                        if trigger_iter < 0:
                            #Plot triggers
                            plt.figure()
                            plt.title(electrode + (', peak score: ' + str(peak_score)) if peak_filtering else '')
                            plt.plot(((np.array(range(len(chunk)))) - pre_stimuli)/fs, chunk, 'g-', linewidth=1)
                            plt.axvline(0, color='k', linestyle='dashed')
                            plt.axvline(0.17, color='b', linestyle='dashed')
                            plt.xlabel('Time [s]')
                            plt.ylabel('uV')
                            plt.grid()
                            plt.savefig("figures\\" + basename(filename) + "\\chunks\\"+electrode+'_'+str(trigger_iter)+ ('_common' if common_avg_ref else '_org') +'.png')
                            plt.close()

                        if chunk_peak_to_peak < chunk_max_peak_to_peak and peak_score > min_peak_score:
                            try:
                                face_id = record['order'][trigger_iter][0]
                                if len(record['order']) > 0 and is_face_angry(face_id):
                                    extracted_chunks_angry2[electrode].append(chunk)
                                elif len(record['order']) > 0 and is_face_happy(face_id):
                                    extracted_chunks_happy2[electrode].append(chunk)
                                elif len(record['order']) > 0:
                                    extracted_chunks_neutral2[electrode].append(chunk)
                            except:
                                pass

            i += max_trigger_peak_width
            trigger_iter += 1
        else:
            i += 1

    # Calculate difference between true timestamps and openvibe timestamps
    # diff = np.subtract(true_timestamps[:len(openvibe_timestamps)], openvibe_timestamps)
    # m = np.mean(diff)
    # v = np.std(diff)
    print(filename)


######### AVERAGE CHUNKS ##################
invert_y_axis = False

# N170 area 140-185ms
n170_begin = pre_stimuli + time2sample(0.12)
n170_end = pre_stimuli + time2sample(0.19)

for electrode in electrodes_to_analyze:

    chunks_angry = extracted_chunks_angry[electrode]
    chunks_happy = extracted_chunks_happy[electrode]
    chunks_neutral = extracted_chunks_neutral[electrode]

    chunks_angry2 = extracted_chunks_angry2[electrode]
    chunks_happy2 = extracted_chunks_happy2[electrode]
    chunks_neutral2 = extracted_chunks_neutral2[electrode]

    if len(chunks_angry) == 0 or len(chunks_neutral) == 0 or len(chunks_happy) == 0:
        continue

    # Grand-average over all chunks
    averaged_angry = np.mean(chunks_angry, axis=0)
    averaged_happy = np.mean(chunks_happy, axis=0)
    averaged_neutral = np.mean(chunks_neutral, axis=0)
    averaged_total = np.mean(np.concatenate((chunks_neutral, chunks_angry, chunks_happy)), axis=0)
    baseline = np.mean(averaged_total[:pre_stimuli + 1])

    # Grand-average over all chunks
    averaged_angry2 = np.mean(chunks_angry2, axis=0)
    averaged_happy2 = np.mean(chunks_happy2, axis=0)
    averaged_neutral2 = np.mean(chunks_neutral2, axis=0)
    averaged_total2 = np.mean(np.concatenate((chunks_neutral2, chunks_angry2, chunks_happy2)), axis=0)
    baseline2 = np.mean(averaged_total2[:pre_stimuli + 1])

    # change voltage scale as difference from baseline
    averaged_angry -= baseline
    averaged_happy -= baseline
    averaged_neutral -= baseline

    # change voltage scale as difference from baseline
    averaged_angry2 -= baseline2
    averaged_happy2 -= baseline2
    averaged_neutral2 -= baseline2

    # TODO: take into account invert_axis
    peaks_angry = scipy.signal.find_peaks_cwt(averaged_angry, np.arange(1, 10))
    n170_index = np.argmin(averaged_angry[n170_begin:n170_end]) + n170_begin
    previous_peak_angry = max([x for x in peaks_angry if x < n170_index]) - 1
    vpp_angry = averaged_angry[previous_peak_angry] - averaged_angry[n170_begin:n170_end].min()

    peaks_happy = scipy.signal.find_peaks_cwt(averaged_happy, np.arange(1, 10))
    n170_index = np.argmin(averaged_happy[n170_begin:n170_end]) + n170_begin
    previous_peak_happy = max([x for x in peaks_happy if x < n170_index]) - 1
    vpp_happy = averaged_angry[previous_peak_happy] - averaged_happy[n170_begin:n170_end].min()

    peaks_neutral = scipy.signal.find_peaks_cwt(averaged_neutral, np.arange(1, 10))
    n170_index = np.argmin(averaged_neutral[n170_begin:n170_end]) + n170_begin
    previous_peak_neutral = max([x for x in peaks_neutral if x < n170_index]) - 1
    vpp_neutral = averaged_neutral[previous_peak_neutral] - averaged_neutral[n170_begin:n170_end].min()

    print(vpp_angry, vpp_happy, vpp_neutral)
    writer.writerow([basename(filename), electrode, vpp_angry, vpp_happy, vpp_neutral, len(chunks_angry), len(chunks_happy), len(chunks_neutral)])

    plt.figure()
    plt.title(suffix + ' - ' + electrode + ' - ' + str(len(chunks_angry)) + '/' + str(len(chunks_happy)) + '/' + str(len(chunks_neutral)) + ' - ' + str(len(chunks_angry2)) + '/' + str(len(chunks_happy2)) + '/' + str(len(chunks_neutral2)) +' chunks average')
    plt.plot(np.multiply(np.arange(len(averaged_angry)) - pre_stimuli, 1000 / fs), averaged_angry, color='r', linestyle="dashed")
    plt.plot(np.multiply(np.arange(len(averaged_angry2)) - pre_stimuli, 1000 / fs), averaged_angry2, color='r')
    plt.plot(np.multiply(np.arange(len(averaged_happy)) - pre_stimuli, 1000 / fs), averaged_happy, color='b', linestyle="dashed")
    plt.plot(np.multiply(np.arange(len(averaged_happy2)) - pre_stimuli, 1000 / fs), averaged_happy2, color='b')
    plt.plot(np.multiply(np.arange(len(averaged_neutral)) - pre_stimuli, 1000 / fs), averaged_neutral, color='#808080', linestyle="dashed")
    plt.plot(np.multiply(np.arange(len(averaged_neutral2)) - pre_stimuli, 1000 / fs), averaged_neutral2, color='#808080')
    plt.axvline(0, color='k', linestyle='dashed')
    plt.axhline(0, color='k', linestyle='dashed')
    plt.ylim([-15.0, 7.5])
    plt.yticks(np.arange(-15.0, 8, 2.5))
    plt.xlabel('Time [ms]')
    plt.ylabel('uV')
    if invert_y_axis:
        plt.gca().invert_yaxis()
    figure_file = "figures\\" + basename(filename) + "\\erp\\" + electrode + ('_common_' if common_avg_ref else '_org_') + str(int(filter_on*high_cutoff)) + 'Hz' + suffix
    figure_file_all = "figures\\all\\" + electrode + ('_common_' if common_avg_ref else '_org_') + (('peak-filtered_' + str(min_peak_score) + '_') if peak_filtering else '') + str(int(filter_on * high_cutoff)) + 'Hz' + suffix
    plt.savefig(figure_file + '.png')
    plt.savefig(figure_file_all + '.png')
    plt.savefig(figure_file_all + '.eps')
    #plt.show()

    # print(electrode)
    # print(len(chunks_emo), '\t', len(chunks_neutral))
    # print(averaged_emo[n170_begin:n170_end].min(), '\t', averaged_neutral[n170_begin:n170_end].min())

print('\n')
