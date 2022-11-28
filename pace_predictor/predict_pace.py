# -*- coding: UTF-8 -*- #
"""
@filename:predict_pace.py
@author:201300086
@time:2022-11-26
"""
from pedestrian_data import PedestrianDataset, do_not_mask
from geopy.distance import geodesic
import math
from scipy.signal import find_peaks
from scipy.optimize import minimize
import scipy.optimize
from evaluate.test import get_dist_error_meters,get_dist_train_error_meters
from locus_predictor.helper import record_time
import numpy as np
import pandas as pd
import os

MIN_PERIOD = 20
PROMINENCE = (0.05, None)
Magic_A = 0.37
Magic_B = 0.000155
Magic_C = 0.1638
import matplotlib
import scipy
import matplotlib.pyplot as plt
from locus_predictor.mature_locus_predictor import locus_predictor, __simulated_walk, __aligned_with_gps
from plot_dataset import plot_locus
from pace_predictor.acc_pace_inference import ema, pace_inference



Train_rate = 0.1  # 使用前10%标记预测步幅


# def baseline_pace_inference(info):
#     locus=info['locus']
#     transform = 1
#
#     if (info["inference_times"] == 1):
#         positions = info["gps_positions_temp"]
#         positions=positions-positions[0]
#
#         positions=positions.T
#         Lati = locus.relative_location["relative_x (m)"].to_numpy()
#         Longi = locus.relative_location["relative_y (m)"].to_numpy()
#         last_index = int(Train_rate * len(Lati)) - 1
#         start_to_end_positions = np.linalg.norm(np.array([positions[0][last_index], positions[1][last_index]]) - np.array([positions[0][0], positions[1][0]]))
#         start_to_end_GPS = np.linalg.norm(np.array([Lati[last_index], Longi[last_index]]) - np.array([Lati[0], Longi[0]]))
#         #print("Compare before correction:",start_to_end_positions,start_to_end_GPS)
#         transform = start_to_end_GPS/start_to_end_positions#pace整体乘一个比例
#         #print(transform)
#
#
#     #总位移除步数
#     walk_direction_bias=info['walk_direction_bias']
#     Lati = locus.relative_location["relative_x (m)"].to_numpy()
#     Longi = locus.relative_location["relative_y (m)"].to_numpy()
#     start_to_end_GPS= np.linalg.norm(np.array([Lati[-1],Longi[-1]]) - np.array([Lati[0],Longi[0]]))
#
#     dist_list=[]
#     dist_list_whole=[]
#     normal_step=0
#     for i in range(0,int(len(Lati) * Train_rate)):
#         vec1=np.array([Lati[i],Longi[i]])
#         vec2=np.array([Lati[i+1],Longi[i+1]])
#         dist = np.linalg.norm(vec1 - vec2)#欧氏距离
#         #print(dist)
#         dist_list_whole.append(dist)
#         if dist<0.75:#dist>0.6 and
#             dist_list.append(dist)
#             dist_list_whole.append(dist)
#             normal_step+=1
#     dist_list=np.array(dist_list)
#     dist_list_whole = np.array(dist_list_whole)
#
#     def inference(index, peak):
#         if not normal_step==0:
#             pace=dist_list.sum()/normal_step
#         else:
#             pace=dist_list_whole.sum()/len(dist_list_whole)
#         #print("baseline pace=",pace,normal_step)
#         return pace * transform
#
#     return inference
#
#
# def idiot_pace_inference(info):
#     def inference(index, peak):
#         return 0.8
#     return inference


def magic_pace_inference(info):
    accelerations = info["accelerations"]
    magic_number = info['magic']
    print(magic_number)
    a_vec = np.sqrt(np.power(accelerations[:, 0], 2) + np.power(accelerations[:, 1], 2))
    time = info["time"]
    peaks_index, _ = find_peaks(a_vec, distance=MIN_PERIOD, prominence=PROMINENCE)
    walk_time = time[peaks_index]
    steplength = []

    for i in range(len(walk_time) - 1):
        W = (walk_time[i] if i == 0 else walk_time[i + 1] - walk_time[i]) * 1000
        peak = (a_vec[peaks_index[i + 1]] + a_vec[peaks_index[i]]) / 2
        valley = np.min(a_vec[peaks_index[i]:peaks_index[i + 1]])
        H = peak - valley
        magic_num = magic_number[0] - magic_number[1] * W + magic_number[2] * math.sqrt(H)
        steplength.append(magic_num)
    steplength = np.array(steplength)  # .clip(0.6, 0.75)

    # print("pace predict mean:",steplength.mean())

    def inference(index, peak):
        return steplength[index] if index < len(steplength) else ema(np.asarray(steplength))

    return inference


def save_output(position, location_time, output_path, locus):
    df = pd.DataFrame(position)
    df["Time (s)"] = location_time
    df = df.iloc[:, [2, 0, 1]]
    df.columns = ["Time (s)", "Latitude (°)", "Longitude (°)"]
    # df.to_csv(os.path.join(output_path, "Location_output.csv"), sep=',', index=False)
    # gt = pd.read_csv(os.path.join(output_path, "Location.csv"))
    # pred = pd.read_csv(os.path.join(output_path, "Location_output.csv"))
    gt = locus.relative_location.iloc[:, [0, 3, 4]]
    pred = df
    #后90%GPS算分
    #dist_error = get_dist_error_meters(gt, pred)
    #前10%GPS算分
    dist_error = get_dist_train_error_meters(gt, pred)
    print("error：", dist_error)
    return dist_error


def search_func_bias(walk_direction_bias, *args):
    locus, location_time, output_path = args
    predictor_base = locus_predictor(pace_inference=magic_pace_inference, walk_direction_bias=walk_direction_bias)
    (position, direction), info = predictor_base(locus, )
    return save_output(position, location_time, output_path, locus)


def search_func_magic(all_magic, *args):
    locus, location_time, output_path = args
    walk_direction_bias = all_magic[0]
    magic = all_magic[-3:]
    predictor_base = locus_predictor(pace_inference=magic_pace_inference,
                                     walk_direction_bias=walk_direction_bias, magic=magic)
    (position, direction), info = predictor_base(locus, )

    return save_output(position, location_time, output_path, locus)


def plot_result(data):
    #data_dir="Hand-Walk"
    data_dir="test_case0"
    path_dir="C:\\Users\\Shawn\\Desktop\\python_work\\pytorch\\Dataset-of-Pedestrian-Dead-Reckoning"
    path =os.path.join(path_dir, data_dir)
    #path = "C:\\Users\\Shawn\\Desktop\\python_work\\pytorch\\Dataset-of-Pedestrian-Dead-Reckoning\\test_case0"
    #path = "C:\\Users\\Shawn\\Desktop\\python_work\\pytorch\\Dataset-of-Pedestrian-Dead-Reckoning\\TestSet"
    output_path = os.path.join(path, data)
    dataset = PedestrianDataset([data_dir], window_size=1000, mask=do_not_mask())
    locus = dataset[data]
    location_time = locus.y_frame["location_time"]

    # predictor_base = locus_predictor(pace_inference=baseline_pace_inference,walk_direction_bias=0.27)

    # 寻最优bias:针对baseline
    # x0 = np.asarray(0)
    # bias=minimize(search_func_bias, x0, args=(locus, location_time, output_path),tol=1e-3,options={'maxiter':50})
    # #bias = scipy.optimize.fmin_cg(search_func_bias, x0, args=(locus, location_time, output_path))
    # print("bias",bias)
    # bias=bias['x']

    # plot baseline
    # predictor_base = locus_predictor(pace_inference=baseline_pace_inference, walk_direction_bias=bias)
    # (position,direction),info=predictor_base(locus,)
    # save_output(position,location_time,output_path,locus)
    # plot_locus(position.T[0],position.T[1],label='bias:{}'.format(bias))
    @record_time
    def find_bias():
        # 寻最优bias:针对magic_pace_inference
        x0 = np.asarray(0)
        bias = minimize(search_func_bias, x0, args=(locus, location_time, output_path))
        print("bias", bias)
        bias ,error= bias['x'],bias['fun']

        #bias=[0.35821358]
        predictor_acc = locus_predictor(pace_inference=magic_pace_inference, walk_direction_bias=bias)
        (position, direction), info = predictor_acc(locus)
        save_output(position, location_time, output_path, locus)
        plot_locus(position.T[0], position.T[1], label='bias_only:{}'.format(error))

    @record_time
    def find_magic():
        # 寻最优magic：针对magic_pace_inference
        x0 = np.asarray([Magic_A,Magic_B,Magic_C])
        # all_magic = scipy.optimize.fmin_cg(search_func_magic, x0, args=(locus, location_time, output_path))
        magic = minimize(search_func_magic, x0, args=(locus, location_time, output_path)
                             , tol=1e-2, options={'maxiter': 20, 'disp': True})
        print("magic", magic)
        magic,error = magic['x'],magic['fun']
        # magic=[0.36171501, 0.00148213, 0.5621904 ]
        # error = 1
        predictor_acc = locus_predictor(pace_inference=magic_pace_inference, walk_direction_bias=0,
                                        magic=magic)
        (position, direction), info = predictor_acc(locus)
        save_output(position, location_time, output_path, locus)
        plot_locus(position.T[0], position.T[1], label='magic_only:{}'.format(error))

    @record_time
    def find_all_magic():
        # 寻所有参数：针对magic_pace_inference
        x0 = np.asarray([0, Magic_A,Magic_B,Magic_C])
        # all_magic = scipy.optimize.fmin_cg(search_func_magic, x0, args=(locus, location_time, output_path))
        all_magic = minimize(search_func_magic, x0, args=(locus, location_time, output_path)
                             , tol=1e-2, options={'maxiter': 20, 'disp': True})
        print("all_magic", all_magic)
        all_magic,error = all_magic['x'],all_magic['fun']

        #all_magic=[  0.30234795,  -0.42075507, 229.81865892,  -0.89270903]
        predictor_acc = locus_predictor(pace_inference=magic_pace_inference, walk_direction_bias=all_magic[0],
                                        magic=all_magic[1:])
        (position, direction), info = predictor_acc(locus)
        save_output(position, location_time, output_path, locus)
        plot_locus(position.T[0], position.T[1], label='acc_pace:{}'.format(error))

    def plot_GPS():
        # plot GPS
        # Lati = locus.relative_location["relative_x (m)"].to_numpy()
        # Longi = locus.relative_location["relative_y (m)"].to_numpy()
        Lati = locus.ans_relative_location["relative_x (m)"].to_numpy()
        Longi = locus.ans_relative_location["relative_y (m)"].to_numpy()
        plot_locus(Lati, Longi, label='GPS')
        plt.title(data)

    #find_bias()
    find_magic()
    # find_all_magic()
    plot_GPS()

# plot_result("Hand-Walk-02-001")#[-2.00753911e-01,  5.69380802e-01, -8.49469774e-05,  5.27603339e-02]
# plot_result("Hand-Walk-02-002")#[ 1.50019425,  0.89199096, -0.00565934, -2.25026012]

if __name__ == "__main__":
    matplotlib.use('TkAgg')
    # 78不要
    # plt.subplot(221)
    # plot_result("Hand-Walk-02-006")
    # plt.subplot(222)
    # plot_result("Hand-Walk-02-009")
    # plt.subplot(223)
    # plot_result("Hand-Walk-02-003")
    # plt.subplot(224)
    # plot_result("Hand-Walk-02-005")
    #plot_result("Hand-Walk-02-004")
    plot_result("test_case0-00-000")
    plt.show()
