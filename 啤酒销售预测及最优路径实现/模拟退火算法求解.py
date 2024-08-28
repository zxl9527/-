import pandas as pd
import requests
import time
import random
import math
import os
import json
import concurrent.futures
from datetime import datetime
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

API_KEY = 'b0a39d94b88e215bb5ad145442cd157a'

# 添加全局缓存
lat_lon_cache = {}
distance_cache = {}

# 使用有序字典存储地址及其经纬度
addresses_dict = OrderedDict()

def get_lat_lon_amap(address, api_key):
    if address in lat_lon_cache:
        return lat_lon_cache[address]

    base_url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "address": address,
        "key": api_key
    }
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        results = response.json().get('geocodes')
        if results:
            location = results[0]['location']
            lon, lat = location.split(',')
            lat_lon_cache[address] = (lat, lon)
            return lat, lon
    return None, None

def get_driving_route_distance(origin, destination, api_key, delay=0.035):
    cache_key = (origin, destination)
    if cache_key in distance_cache:
        return distance_cache[cache_key]

    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        'key': api_key,
        'origin': origin,
        'destination': destination,
        'output': 'json'
    }
    time.sleep(delay)
    response = requests.get(url, params=params)
    if response.status_code == 200:
        distance = response.json().get('route', {}).get('paths', [{}])[0].get('distance')
        if distance is not None:
            try:
                distance = int(distance)
                distance_cache[cache_key] = distance
                return distance
            except ValueError:
                print(f"无法将距离转换为整数: {distance}")
    return 0  # 默认值

def process_address(address):
    lat, lon = get_lat_lon_amap(address, API_KEY)
    if lat and lon:
        address_key = f"{lon},{lat}"
        if address_key not in addresses_dict:
            addresses_dict[address_key] = address
            return address_key
    return None

def cache_all_distances(addresses, api_key):
    num_addresses = len(addresses)
    total_pairs = num_addresses * (num_addresses - 1) // 2

    with tqdm(total=total_pairs, desc="计算地址对之间的距离") as pbar:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(num_addresses):
                for j in range(i + 1, num_addresses):
                    addr1 = addresses[i]
                    addr2 = addresses[j]
                    if addr1 != addr2:
                        futures.append(executor.submit(get_driving_route_distance, addr1, addr2, api_key, delay=0.035))

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"计算距离时出错: {e}")
                pbar.update(1)

def calculate_route_cost(route, addresses):
    total_cost = 0
    for i in range(len(route) - 1):
        start = addresses[route[i]]
        end = addresses[route[i + 1]]
        cache_key = (start, end)

        if cache_key in distance_cache:
            distance = distance_cache[cache_key]
        else:
            distance = get_driving_route_distance(start, end, API_KEY)
            if distance is not None:
                distance_cache[cache_key] = distance

        total_cost += distance
    return total_cost


def generate_initial_route_heuristic(addresses, warehouse):
    print("算法正在计算中，请稍等...")
    route = [0]
    current_address = warehouse
    unvisited = list(addresses_dict.keys())
    unvisited.remove(warehouse)

    def find_closest_address(curr_address):
        distances = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for address in unvisited:
                futures.append(executor.submit(get_driving_route_distance, curr_address, address, API_KEY))

            for address, future in zip(unvisited, futures):
                try:
                    distance = future.result()
                    distances[address] = distance
                except Exception as e:
                    print(f"计算距离时出错: {e}")

        closest = min(distances, key=distances.get)
        return closest

    while unvisited:
        closest = find_closest_address(current_address)
        closest_index = list(addresses_dict.keys()).index(closest)
        route.append(closest_index)
        current_address = closest
        unvisited.remove(closest)

    route.append(0)
    return route


def simulated_annealing(addresses, api_key, initial_temp, cooling_rate, final_temp, max_iter, warehouse):
    if len(addresses) <= 2:
        raise ValueError("地址数量不足，无法生成有效路径")

    current_route = generate_initial_route_heuristic(addresses, warehouse)
    current_cost = calculate_route_cost(current_route, addresses)

    best_route = current_route[:]
    best_cost = current_cost

    temp = initial_temp
    iter_count = 0

    def swap_and_calculate(new_route, i, j):
        new_route[i], new_route[j] = new_route[j], new_route[i]
        new_cost = calculate_route_cost(new_route, addresses)
        return new_route, new_cost

    with tqdm(desc="模拟退火进度", total=max_iter) as pbar:  # 添加 total 参数
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            while temp > final_temp and iter_count < max_iter:
                futures = []
                for _ in range(10):
                    new_route = current_route[:]
                    if len(new_route) > 2:
                        i, j = random.sample(range(1, len(new_route) - 1), 2)
                        futures.append(executor.submit(swap_and_calculate, new_route, i, j))

                for future in concurrent.futures.as_completed(futures):
                    new_route, new_cost = future.result()

                    if new_cost < current_cost or random.random() < math.exp((current_cost - new_cost) / temp):
                        current_route = new_route
                        current_cost = new_cost

                        if new_cost < best_cost:
                            best_route = new_route[:]
                            best_cost = new_cost

                temp *= cooling_rate
                iter_count += 1
                pbar.update(1)  # 直接使用 update(1) 来增加进度条的进度
                pbar.set_postfix(temperature=f"{temp:.2f}")

    return best_route, best_cost

def write_to_template_xlsx(route, file_path):
    # 读取模板文件
    df_template = pd.read_excel(file_path, engine='openpyxl')

    # 清除模板文件中的数据
    df_template = df_template.iloc[0:0]

    # 准备数据
    lat_lon_data = []
    for index in route:
        # 将索引映射到地址
        address = list(addresses_dict.values())[index]
        lat, lon = get_lat_lon_amap(address, API_KEY)
        lat_lon_data.append([lon, lat])

    # 添加数据到 DataFrame
    df_template = pd.DataFrame(lat_lon_data, columns=['*经度', '*纬度'])

    # 保存更新后的文件
    df_template.to_excel(file_path, index=False)
    print(f"最优路径经纬度已写入到 {file_path}")

def update_path(addresses, api_key, warehouse):
    try:
        best_route, best_cost = simulated_annealing(addresses, api_key, initial_temp=1000, cooling_rate=0.98,
                                                    final_temp=1, max_iter=500, warehouse=warehouse)

        # 生成路径时避免重复起点和终点
        best_route_addresses = [addresses[i] for i in best_route]

        # 去重处理，确保路径中不会重复地址
        unique_route_addresses = []
        seen = set()
        for address in best_route_addresses:
            if address not in seen:
                unique_route_addresses.append(address)
                seen.add(address)

        print(f"当前最优路径：{unique_route_addresses}")
        print(f"当前最优路径成本：{best_cost}")

        output_path = 'optimal_path.json'
        with open(output_path, 'w') as f:
            json.dump(unique_route_addresses, f)
        print(f"新的最优路径已保存到 {output_path}")

        # 添加将经纬度写入模板.xlsx 的功能
        template_path = '导入模板.xlsx.xlsx'
        write_to_template_xlsx(best_route, template_path)

    except ValueError as e:
        print(f"路径规划出错: {e}")


if __name__ == "__main__":
    # 读取文件并处理数据
    upload_folder = 'uploads'

    files = os.listdir(upload_folder)
    if not files:
        raise ValueError("上传文件夹中没有文件")
    file_path = os.path.join(upload_folder, files[0])

    input_date = input("请输入要处理的日期（比如：2024/05/20）：")

    encodings_to_try = ['utf-8', 'gb18030', 'GBK']
    data_read = False
    date_found = False
    addresses = []

    for encoding in encodings_to_try:
        try:
            file_ext = file_path.lower().rsplit('.', 1)[1]
            if file_ext == 'csv':
                data = pd.read_csv(file_path, encoding=encoding)
            else:
                data = pd.read_excel(file_path, engine='openpyxl')

            print(f"使用编码 {encoding} 读取文件成功。")

            input_date_obj = datetime.strptime(input_date, "%Y/%m/%d").date()

            with ThreadPoolExecutor() as executor:
                futures = []
                for index, row in data.iterrows():
                    date_str = row['日期']
                    address = row['地址']

                    if isinstance(date_str, pd.Timestamp):
                        date = date_str.to_pydatetime().date()
                    else:
                        try:
                            date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        except ValueError:
                            continue

                    if address and date == input_date_obj:
                        futures.append(executor.submit(process_address, address))
                        date_found = True

                for future in as_completed(futures):
                    address_key = future.result()
                    if address_key:
                        addresses.append(address_key)

            data_read = True
            break

        except Exception as e:
            print(f'读取文件时出错: {e}')

    if not data_read:
        print("无法读取文件，请检查文件编码格式。")
    elif not addresses:
        print("未提取到有效地址，请检查输入日期和文件内容。")
    else:
        warehouse = '106.480936,29.460931'
        addresses_dict[warehouse] = warehouse

        if len(addresses_dict) <= 1:
            raise ValueError("未提取到有效地址，请检查输入日期和文件内容。")
        start_time = time.time()
        cache_all_distances(list(addresses_dict.keys()), API_KEY)
        end_time = time.time()

        elapsed_time = end_time - start_time
        print(f"预计算所有地址对之间的距离耗时: {elapsed_time:.2f}秒")

        update_path(list(addresses_dict.keys()), API_KEY, warehouse)

        cancel_order = input("是否有订单取消需求？(y/n): ").lower()
        if cancel_order == 'y':
            cancel_place = input("请输入取消订单的地址：")
            cancel_lat, cancel_lon = get_lat_lon_amap(cancel_place, API_KEY)
            if cancel_lat and cancel_lon:
                cancel_address = f"{cancel_lon},{cancel_lat}"
                if cancel_address in addresses_dict:
                    del addresses_dict[cancel_address]
                    print(f"取消订单地址已删除：{cancel_place}，经度：{cancel_lon}, 纬度：{cancel_lat}")
                else:
                    print("取消订单地址不在路径中。")
                update_path(list(addresses_dict.keys()), API_KEY, warehouse)
            else:
                print("无法获取取消订单地址的经纬度，取消操作失败。")

        add_order = input("是否有订单添加需求？(y/n): ").lower()
        if add_order == 'y':
            new_place = input("请输入新增订单的地址：")
            add_lat, add_lon = get_lat_lon_amap(new_place, API_KEY)
            if add_lat and add_lon:
                new_address = f"{add_lon},{add_lat}"
                if new_address not in addresses_dict:
                    addresses_dict[new_address] = new_place
                    print(f"新增订单地址已添加：{new_place}，经度：{add_lon}, 纬度：{add_lat}")
                else:
                    print("新增订单地址已经存在于路径中。")
                update_path(list(addresses_dict.keys()), API_KEY, warehouse)
            else:
                print("无法获取新增订单地址的经纬度，添加操作失败。")
