import re
import time
import random
import os.path
import numpy as np
import pandas as pd
import pickle
import operator

# 显示配置，便于在命令台显示完整结果
pd.set_option('display.max_columns', 10000)
pd.set_option('display.width', 1000)
pd.set_option('display.max_colwidth', 10000)

# 程序可调整的相关参数
r_limit = 1                 # 构建转移矩阵的阈值（低于这个数值的数据不计入转移矩阵）
W = 1                       # 搜索宽度（每轮预测最多加入多少个可能的预测值）
D = 20                      # 搜索深度（最多预测多少个元素）
test_is_strict  = 0         # 是否采用严格定义（0表示广义，非0表示严格）
bool_print      = False     # 是否在终端print输出具体的事务工作集（预测和实际）
bool_temp_file  = False     # 是否生成临时文件记录转移矩阵等信息

conf_index      =   1
log_directory   =   "1000"
log_train_file  =   "./log/" + log_directory + "/log_train"     # 这个文件是用来训练转移矩阵的
log_test_file   =   "./log/" + log_directory + "/log_test"      # 这个文件是用来测试预测效果的（理论上和训练日志不能是同一个文件，最好是同样的工作负载生成的另一份日志）

# 数据项的编号及记录
data_total = 1      # 出现过的数据项数量总和
data_dict = {}      # 数据项及其对应编号

# 数据项出现次数及转移矩阵
count_vxid = {}                 # 记录事务中已出现的SQL操作数（不包括BEGIN/COMMIT等）
txn_last_is_write = {}          # 记录事务上一个访问的方式（虚拟事务ID → 0/1）
data_matrix_dict = {}           # 记录转移矩阵（数据项1的编号 → 与该数据项相邻的其他数据项及转移概率（数据项2的编号 → 相邻次数/数据项1出现的总次数））
data_write_matrix_dict = {}     # 记录转移矩阵（数据项的编号 → 该数据项是读或写的次数（2个数字构成的list））

txn_workingset = {}          # 当前并发事务的工作集（预测）
real_txn_workingset = {}     # 事务的工作集（实际）
record_workingset = {}       # 记录的事务工作集（预测）
pre_isolevel_dict = {}       # 预测的隔离级别（虚拟事务ID → 隔离级别 123表示）

def find_key_by_value(my_dict, value):
    for key, val in my_dict.items():
        if val == value:
            return key
    return None

# # 保存数据到文件
# def save_to_file(filename, data):
#     with open(filename, 'wb') as file:
#         pickle.dump(data, file)

# 辅助算法：找出字典中概率最大的num项，如果不足num项则有多少返回多少项
def getDictMaxW(dict, num):
    if len(dict) == 0:
        return set()
    list_keys = []
    list_values = []
    for key in dict:
        if key != "NUM":
            list_keys.append(key)
            list_values.append(float(dict[key]["NUM"])/float(dict["NUM"]))
    list_output = []
    i = 0
    while i < min(num, len(list_keys)):
        i = i + 1
        j = len(list_keys)-1
        while j > 0:
            if list_values[j-1] < list_values[j]:
                temp_value = list_values[j-1]
                list_values[j-1]  = list_values[j]
                list_values[j]  = temp_value
                temp_key = list_keys[j-1]
                list_keys[j-1]  = list_keys[j]
                list_keys[j]  = temp_key
            j = j - 1
    for k in range(0, i):
        list_output.append(list_keys[k])
    return list_output

def getListMaxW(list, num):
    output = []
    i = 0
    while i < min(num, len(list)):
        i = i + 1
        j = len(list) - 1
        while j > 0:
            if list[j-1][1] < list[j][1]:
                temp_tuple = list[j-1]
                list[j-1] = list[j]
                list[j] = temp_tuple
            j = j - 1
    for k in range(0, i):
        output.append(list[k])
    return output

data_item_hash = {}

# 获取数据项编号的算法，根据SQL语句获取数据项的编号
# 输入：一个SQL语句，须是SELECT/UPDATE/DELETE/INSERT中的一种
# 返回：该SQL语句访问的数据项的编号，如果没有访问数据项或语句类型不对，则返回-1
def getDataId(statement):
    global data_total
    global data_dict
    global data_index_hash

    dataId = -1
    query_type = ""
    query_condition = ""

    # SELECT 语句分析
    if statement.upper().startswith("SELECT"):
        query_type = "SELECT"
        if statement.find("WHERE") != -1:
            query_condition = statement[statement.index("WHERE") + 6:].strip()
        else:
            query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

    # UPDATE 语句分析
    elif statement.upper().startswith("UPDATE"):
        query_type = "UPDATE"
        if statement.find("WHERE") != -1:
            query_condition = statement[statement.index("WHERE") + 6:].strip()
        else:
            query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

    # DELETE 语句分析
    elif statement.upper().startswith("DELETE"):
        query_type = "DELETE"
        if statement.find("WHERE") != -1:
            query_condition = statement[statement.index("WHERE") + 6:].lstrip()
        else:
            query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

    # INSERT 语句分析
    elif statement.upper().startswith("INSERT"):
        query_type = "INSERT"
        if statement.upper().find("VALURS") != -1:
            insert = re.sub('\"', '', re.search(r'INTO (.*?) VALUES', statement, re.I).group(1)).strip()
        else:
            return -1, query_type
        if insert.find("(") == -1:
            insert_key = "ALL"
        else:
            insert_key = insert.split("(")[1].split(")")[0].strip()
            insert_value = re.search(r"VALUES\((.*?)\)", statement).group(1).strip()
        query_condition = insert_key + "=" + insert_value

    # BEGIN 分析
    elif (statement.upper().startswith("BEGIN")) or (statement.upper().startswith("START")):
        query_type = "BEGIN"
    # COMMIT 分析
    elif (statement.upper().startswith("END")) or (statement.upper().startswith("COMMIT")):
        query_type = "COMMIT"
    # ROLLBACK 分析
    elif (statement.upper().startswith("ROLLBACK")) or (statement.upper().startswith("ABORT")):
        query_type = "ROLLBACK"
    # 其他
    else:
        query_type = "OTHERS"

    # 获取数据项编号
    if (query_condition not in data_dict) and query_condition != "":
        data_dict[query_condition] = data_total
        data_total = data_total + 1
        dataId = data_total - 1
    elif query_condition in data_dict:
        data_index = data_dict[query_condition]
        dataId = data_index
    elif query_condition == "ALL":
        dataId = 0 # 数据项编号为0表示全表访问（即没有查询条件，访问整个表的数据）
    else:
        dataId = -1  # 数据项编号为-1表示没有访问数据项

    if dataId in data_matrix_dict and dataId != -1:
        data_matrix_dict[dataId]["NUM"] += 1
    elif dataId != -1:
        data_matrix_dict[dataId] = {}
        data_matrix_dict[dataId]["NUM"] = 1

    return dataId, query_type

def read_csv_data(logFile):
    global data_total
    global r_limit

    # 读取原始数据，手动重命名各列的属性名
    colNames = ['TIME', 'VXID', 'XID', 'LOG', 'DETAIL','A','B', 'C']
    dataset = pd.read_csv(logFile, header=None, names=colNames, dtype='str')

    # 去除虚拟事务ID和LOG内容为空的无用日志记录，以及去掉其他不必要的列
    dataset.drop(dataset[dataset['VXID'] == ''].index, inplace=True)
    dataset.dropna(subset="VXID" ,axis=0, inplace=True)

    # 待添加的新列数据初始化
    sql_Type = []           # 操作类型
    sql_Statement = []      # SQL语句
    sql_data = []           # 访问的数据项编号

    # 按时间顺序排列
    # dataset.sort_values(by="TIME", ascending=True, inplace=True)

    # 补全DETAIL列
    rows_to_delete = []
    aborted_vxid = []
    for index, row in dataset.iterrows():
        if(row["LOG"] is np.nan or row["VXID"] in aborted_vxid):
            rows_to_delete.append(index)  # 删除虚拟事务ID某项为0的行记录
            continue
        # 读取csv文件是根据逗号划分不同列的，因此会出现误判，首先进行处理
        if (len(str(row["DETAIL"])) != 0) and (row["DETAIL"] is not np.nan):
            # 将 row["DETAIL"] 的内容添加到 row["LOG"] 后面
            dataset.loc[index, "LOG"] += " " + str(row["DETAIL"]).strip()
        if (len(str(row["A"])) != 0) and (row["A"] is not np.nan):
            # 将 row["A"] 的内容添加到 row["LOG"] 后面
            dataset.loc[index, "LOG"] += " " + str(row["A"]).strip()
        if (len(str(row["B"])) != 0) and (row["B"] is not np.nan):
            # 将 row["B"] 的内容添加到 row["LOG"] 后面
            dataset.loc[index, "LOG"] += " " + str(row["B"]).strip()
        if (len(str(row["C"])) != 0) and (row["C"] is not np.nan):
            # 将 row["C"] 的内容添加到 row["LOG"] 后面
            dataset.loc[index, "LOG"] += " " + str(row["C"]).strip()
        if str(row["LOG"]).startswith("DETAIL:"):
            dataset.loc[index-1, "DETAIL"] = row["LOG"]
            rows_to_delete.append(index)
            continue
        if (str(row["LOG"]).strip().upper().startswith("STATEMENT") or str(row["LOG"]).strip().upper().startswith("HINT") or str(row["LOG"]).strip().upper().startswith("CONTEXT")  ):
            rows_to_delete.append(index)  # 删除报错
            continue
        if (str(row["VXID"]).split("/")[0].strip() == "0") or (str(row["VXID"]).split("/")[1].strip() == "0"):
            rows_to_delete.append(index) # 删除虚拟事务ID某项为0的行记录
            continue
        if (str(row["LOG"]).upper().startswith("ERROR")):
            aborted_vxid.append(row["VXID"])
            row["LOG"] = "LOG:  execute S_1: ROLLBACK"
            # rows_to_delete.append(index)  # 删除错误数据
            continue

    dataset = dataset.drop(rows_to_delete)
    dataset.drop(['XID', 'A', 'B', 'C'], axis=1, inplace=True)
    dataset = dataset.reset_index(drop=True)

    # 获取新列数据
    for index, row in dataset.iterrows():
        query_type = ""         # 操作类型
        statement = ""          # SQL语句内容
        query_condition = ""    # 查询条件
        data_index = -1         # 访问的数据项编号

        # 获取日志信息中的SQL语句（如果没有日志信息则直接删掉这一行）
        if str(row["LOG"]).find(":") != -1:
            statement = str(row["LOG"])[(str(row["LOG"]).index(":", 5) + 2):].strip('/"').rstrip(';').rstrip()
        else:
            dataset.drop(index, axis=0, inplace=True)
            continue

        # 获取其他属性：操作类型、Where子句
        # SELECT 语句分析
        if statement.upper().startswith("SELECT"):
            query_type = "SELECT"
            if statement.find("WHERE") != -1:
                query_condition = statement[statement.index("WHERE") + 6:].strip()
            else:
                query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

        # UPDATE 语句分析
        elif statement.upper().startswith("UPDATE"):
            query_type = "UPDATE"
            if statement.find("WHERE") != -1:
                query_condition = statement[statement.index("WHERE") + 6:].strip()
            else:
                query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

        # DELETE 语句分析
        elif statement.upper().startswith("DELETE"):
            query_type = "DELETE"
            if statement.find("WHERE") != -1:
                query_condition = statement[statement.index("WHERE") + 6:].lstrip()
            else:
                query_condition = "ALL"  # 如果没有查询条件，说明是全局查询，默认值为ALL

        # INSERT 语句分析 TODO:其实目前还不能很好地处理Insert语句，主要只能处理UPDATE/DELETE/SELECT语句
        elif statement.upper().startswith("INSERT"):
            query_type = "INSERT"
            insert = re.sub('\"', '', re.search(r'INTO (.*?) VALUES', statement, re.I).group(1)).strip()
            if insert.find("(") == -1:
                insert_key = "ALL"
            else:
                insert_key = insert.split("(")[1].split(")")[0].strip()
                insert_value = re.search(r"VALUES\((.*?)\)", statement).group(1).strip()
            query_condition = insert_key + "=" + insert_value

        # BEGIN 分析
        elif (statement.upper().startswith("BEGIN")) or (statement.upper().startswith("START")):
            query_type = "BEGIN"
        # COMMIT 分析
        elif (statement.upper().startswith("END")) or (statement.upper().startswith("COMMIT")):
            query_type = "COMMIT"
        # ROLLBACK 分析
        elif (statement.upper().startswith("ROLLBACK")) or (statement.upper().startswith("ABORT")):
            query_type = "ROLLBACK"
        # 其他
        else:
            query_type = "OTHERS"

        # 若DETAIL列（参数列）不为空，则SQL语句中必包含形如[$i]的参数，利用正则表达式匹配，将参数对应的值替换到SQL语句中
        if (row["DETAIL"] is not np.nan) and (row["DETAIL"] != "")  and (row["DETAIL"].split() != ""):
            temp_parm = row["DETAIL"].strip("\"")[row["DETAIL"].index(":", 7) + 2:].strip().strip(';').strip()  # 获取DETAIL列
            pattern = r'(\$\d+)'  # 待匹配字符：$+数字
            matches = re.findall(pattern, query_condition)  # 匹配结果
            replace_dict = {}  # 将被替换值和替换值以键值对形式储存到字典里
            # 若成功匹配，则将参数中等于号之后的值替换到SQL语句中，替换时去掉参数值前后的单引号
            for match in matches:
                if match in temp_parm:
                    temp_replace = temp_parm.split(match)[-1]
                    # 需要注意有的SQL中不只有一个参数，要防止同时把两个参数的值都替换到同一个参数下
                    temp_match = re.search(r"(.+),\s*\$\d+", temp_replace)
                    if temp_match:
                        replace_dict[match] = temp_match.group(1).strip().lstrip('=').strip()
                    else:
                        replace_dict[match] = temp_replace.strip().lstrip('=').strip()
            # 替换参数值到SQL语句中
            for k, v in replace_dict.items():
                query_condition = query_condition.replace(k, v)
        else:
            temp_parm = ""

        # print("查询条件（数据项）为" + query_condition)

        # 获取数据项编号
        if (query_condition not in data_dict) and query_condition != "":
            data_dict[query_condition] = data_total
            data_index = data_total
            data_total = data_total + 1
        elif query_condition in data_dict:
            data_index = data_dict[query_condition]
        elif query_condition == "ALL":
            data_index = 0      # 数据项编号为0表示全局访问（即没有查询条件，访问整个表的数据）
        else:
            data_index = -1     # 数据项编号为-1表示没有访问数据项

        # 添加获取到的信息到新表中
        sql_Type.append(query_type)
        sql_Statement.append(query_condition)

        DATAITEMSIZE = 2000
        data_index_hash = 0
        if query_condition != "ALL" and query_condition != "":
            data_index_hash = int(query_condition.replace("'", "")[15:]) % DATAITEMSIZE
            data_content = query_condition.replace("'", "")[15:]
            temp_index = data_index_hash
            while data_index_hash in data_item_hash:
                if data_item_hash[data_index_hash] != data_content:
                    data_index_hash = data_index_hash + 1
                    if data_index_hash == DATAITEMSIZE:
                        data_index_hash = 0
                    if temp_index == data_index_hash:
                        data_index_hash = -1
                        break
                else:
                    break
            if data_index_hash != -1:
                data_item_hash[data_index_hash] = data_content
        elif query_condition == "":
            data_index_hash = -1

        sql_data.append(data_index_hash)

    # 添加新列
    dataset["TYPE"] = sql_Type
    dataset["STATEMENT"] = sql_Statement
    dataset["DATA"] = sql_data

    # dataset.drop(['LOG', 'DETAIL', 'LTYPE'], axis=1, inplace=True)
    dataset.drop(['LOG', 'DETAIL'], axis=1, inplace=True)
    dataset.drop(dataset[dataset['TYPE'] == 'OTHERS'].index, inplace=True)
    # dataset.drop(dataset[dataset['TYPE'] == 'INSERT'].index, inplace=True)

    # 去除操作类型为OTHERS类型的行,按时间排序，并更新索引
    dataset.reset_index(drop=True, inplace=True)
    new_name = logFile.rstrip(".csv") + "_new"
    dataset.to_csv(new_name)
    # print(dataset.head(10))
    return dataset


def addToMatrix(list):
    if list[0] not in data_matrix_dict:
        data_matrix_dict[list[0]] = {}
        data_matrix_dict[list[0]]["NUM"] = 1
    temp_matrix = []
    temp_matrix.append(data_matrix_dict[list[0]])
    i = 0
    dlength = len(list)
    while i < dlength-1:
        i = i + 1
        if list[i] in temp_matrix[i-1]:
            temp_matrix[i - 1][list[i]]["NUM"] += 1
            temp_matrix.append(temp_matrix[i-1][list[i]])
        else:
            temp_matrix[i - 1][list[i]] = {}
            temp_matrix[i - 1][list[i]]["NUM"] = 1
            temp_matrix.append(temp_matrix[i - 1][list[i]])

    i = len(temp_matrix)-1
    while i > 0:
        i = i - 1
        temp_matrix[i][list[i+1]] = temp_matrix[i+1]
    data_matrix_dict[list[0]] = temp_matrix[0]
    return data_matrix_dict[list[0]]

# 构造转移矩阵
matrix_2ord = {}
count_data_in_txn = {}
last_data_in_txn = {}
last_last_data_in_txn = {}
data_item_dict = {}  # 记录当前事务的所有工作项
transaction_data_count = {}
def get_matrix_Nord(dataset, percent=1):
    global r_limit
    global count_data_in_txn
    global last_data_in_txn
    global last_last_data_in_txn
    global data_item_dict
    global transaction_data_count

    for index, row in dataset.iterrows():
        if index < len(dataset) * percent:
            # 为了防止虚拟事务ID被复用（两个事务先后用了同一个ID），在每次事务结束时会清空一下之前保留的字典数据
            if row["TYPE"] in ["COMMIT", "ROLLBACK"]:
                if row["VXID"] in data_item_dict:
                    data_item_dict.pop(row["VXID"])
                continue
            elif row["TYPE"] in ["SELECT"]:
                opt_type = 0  # 表示读操作
            elif row["TYPE"] in ["UPDATE", "DELETE", "INSERT"]:
                opt_type = 1  # 表示写操作
            else:
                continue

            DATAITEMSIZE = 2000
            if row["VXID"] not in transaction_data_count:
                transaction_data_count[row["VXID"]] = []

            data_hash = int(row["DATA"]) % DATAITEMSIZE

            if row["DATA"] != -1 and data_hash not in transaction_data_count[row["VXID"]]:
                transaction_data_count[row["VXID"]].append(data_hash)

            # 更新获取到的事务信息，构造转移矩阵
            if row["VXID"] not in data_item_dict:
                empty_item = (-1, -1, -1)
                data_item_dict[row["VXID"]] = (row["DATA"], opt_type, empty_item, 1)  # 数据项，数据读写，上一项数据项，当前数据项数
            else:
                new_item = (row["DATA"], opt_type, data_item_dict[row["VXID"]], data_item_dict[row["VXID"]][3]+1)
                data_item_dict[row["VXID"]] = new_item

            if row["VXID"] in count_data_in_txn:
                count_data_in_txn[row["VXID"]] += 1
            else:
                count_data_in_txn[row["VXID"]] = 1

            if count_data_in_txn[row["VXID"]] == 1:
                if row["DATA"] not in matrix_2ord:
                    matrix_2ord[row["DATA"]] = {}
                last_data_in_txn[row["VXID"]] = row["DATA"]
            elif count_data_in_txn[row["VXID"]] == 2:
                if row["DATA"] not in matrix_2ord[last_data_in_txn[row["VXID"]]]:
                    matrix_2ord[last_data_in_txn[row["VXID"]]][row["DATA"]] = {}
                last_last_data_in_txn[row["VXID"]] = last_data_in_txn[row["VXID"]]
                last_data_in_txn[row["VXID"]] = row["DATA"]
            elif count_data_in_txn[row["VXID"]] > 2:
                if last_last_data_in_txn[row["VXID"]] not in matrix_2ord:
                    matrix_2ord[last_last_data_in_txn[row["VXID"]]] = {}
                if last_data_in_txn[row["VXID"]] not in matrix_2ord[last_last_data_in_txn[row["VXID"]]]:
                    matrix_2ord[last_last_data_in_txn[row["VXID"]]][last_data_in_txn[row["VXID"]]] = {}
                if row["DATA"] not in matrix_2ord[last_last_data_in_txn[row["VXID"]]][last_data_in_txn[row["VXID"]]]:
                    matrix_2ord[last_last_data_in_txn[row["VXID"]]][last_data_in_txn[row["VXID"]]][row["DATA"]] = 1
                else:
                    matrix_2ord[last_last_data_in_txn[row["VXID"]]][last_data_in_txn[row["VXID"]]][row["DATA"]] += 1
                last_last_data_in_txn[row["VXID"]] = last_data_in_txn[row["VXID"]]
                last_data_in_txn[row["VXID"]] = row["DATA"]

            # 计数
            if row["DATA"] in data_matrix_dict:
                data_matrix_dict[row["DATA"]]["NUM"] += 1
                data_write_matrix_dict
            else:
                data_matrix_dict[row["DATA"]] = {}
                data_matrix_dict[row["DATA"]]["NUM"] = 1

            # 读写矩阵
            if row["DATA"] in data_write_matrix_dict:
                data_write_matrix_dict[row["DATA"]][opt_type] += 1
            else:
                temp_list = [0, 0]
                data_write_matrix_dict[row["DATA"]] = temp_list
                data_write_matrix_dict[row["DATA"]][opt_type] += 1

            # 转移矩阵
            temp_item = data_item_dict[row["VXID"]]
            ld = []
            lw = []
            while temp_item[0] != -1:
                ld.append(temp_item[0])
                lw.append(temp_item[1])
                temp_item = temp_item[2]

            if data_item_dict[row["VXID"]][3] == 5:
                addToMatrix([ld[4], ld[3], ld[2], ld[1], ld[0]])
                addToMatrix([ld[4], ld[3], ld[2], ld[1]])
                addToMatrix([ld[3], ld[2], ld[1], ld[0]])
                addToMatrix([ld[4], ld[3], ld[2]])
                addToMatrix([ld[3], ld[2], ld[1]])
                addToMatrix([ld[2], ld[1], ld[0]])
                addToMatrix([ld[4], ld[3]])
                addToMatrix([ld[3], ld[2]])
                addToMatrix([ld[2], ld[1]])
                addToMatrix([ld[1], ld[0]])
            elif data_item_dict[row["VXID"]][3] > 5:
                addToMatrix([ld[4], ld[3], ld[2], ld[1], ld[0]])
                addToMatrix([ld[3], ld[2], ld[1], ld[0]])
                addToMatrix([ld[2], ld[1], ld[0]])
                addToMatrix([ld[1], ld[0]])

    # # 阈值r_limit?

# N阶马尔科夫的束搜索算法
def beam_search_Nord(vxid, data, write_bool, order_num):
    # 预测结果
    P = []
    predict_read_set = []       # 预测的读工作集
    predict_write_set = []      # 预测的写工作集
    predict_data_set = []       # 预测的工作集
    predict_isWrite_set = []    # 预测的工作集读写情况（0读1写）

    # 添加预测结果的初始值 ： data_item_dict
    temp_data_list = []
    temp_write_list = []
    temp_item = data_item_dict[vxid]
    while temp_item[0] != -1:
        temp_data_list.append(temp_item[0])
        temp_write_list.append(temp_item[1])
        temp_item = temp_item[2]

    k = len(temp_data_list)
    while k >0:
        k = k-1
        if k == len(temp_data_list)-1:
            P.append((temp_data_list[k], 1, -1, 0))
        else:
            P.append((temp_data_list[k], 1, temp_data_list[k+1], 0))
        if temp_write_list[k] == 0:
            predict_read_set.append(temp_data_list[k])
        else:
            predict_write_set.append(temp_data_list[k])
        predict_data_set.append(temp_data_list[k])
        predict_isWrite_set.append(temp_write_list[k])

    if write_bool == 1:
        predict_write_set.append(data)
    else:
        predict_read_set.append(data)

    # data_item_dict 元素: (数据项，数据读写，上一项数据项，当前数据项数)

    # 根据概率(转移矩阵）进行预测
    round = 0
    last_Pindex = len(P)-1
    while(round < D - data_item_dict[vxid][3]):
        temp = len(P)
        round = round + 1
        L = []
        for i in range(last_Pindex, len(P)):
            k = temp - order_num
            while k < temp:
                j = k
                if P[j][0] in data_matrix_dict:
                    preList = data_matrix_dict[P[j][0]]
                else:
                    preList = {}
                j = j + 1
                mark = True
                while j < temp:
                    if P[j][0] in preList:
                        preList = preList[P[j][0]]
                    else:
                        mark = False
                        preList = {}
                        break
                    j = j+1
                k = k+1
                if mark:
                    break;
            if mark:
                maxData_list = getDictMaxW(preList, W)
            else:
                maxData_list = {}

            for d in maxData_list:
                tuple_temp = (d, P[i][1] * preList[d]["NUM"]/preList["NUM"], P[i][0], 1)  # 存储的元组格式：（数据项，总概率，上一项， 是否为预测项） P[i][0]表示上一项数据项
                L.append(tuple_temp)
        if len(L) == 0:
            break
        maxTuple_list = getListMaxW(L, W)
        last_Pindex = temp
        for tp in maxTuple_list:
            P.append(tp)

    for tp in P:
        tp = tuple(tp)
        if tp[3] == 0:
            continue
        else:
            is_write = random.choices(population=[0, 1], weights=data_write_matrix_dict[tp[0]])[0]  # 按照该数据项读写操作出现的概率进行随机选择
            if is_write == 0:
                predict_read_set.append(tp[0])
            else:
                predict_write_set.append(tp[0])
            predict_data_set.append(tp[0])
            predict_isWrite_set.append(is_write)
    return predict_read_set, predict_write_set, predict_data_set, predict_isWrite_set

# 输入虚拟事务ID、SQL语句、是否采用严格定义（is_strict为0表示广义，非0表示严格，默认为0），判断隔离级别并print
def rec_txn_isolation(vxid, query_string, is_strict=0, order_num=2, rwPredict=True):
    data, type = getDataId(query_string)

    # 根据预测结果检查异象（预测异象）
    if data != -1:
        if type in ["SELECT"]:
            opt_type = 0  # 表示读操作
        elif type in ["UPDATE", "DELETE", "INSERT"]:
            opt_type = 1  # 表示写操作

        # 统计事务操作数（不计入begin/commit等）
        if vxid in count_vxid:
            count_vxid[vxid] += 1
        else:
            count_vxid[vxid] = 1

        # 获取预测工作集
        read_workingset = []        # 预测的读工作集
        write_workingset = []       # 预测的写工作集
        predict_data_set = []       # 预测的工作集
        predict_isWrite_set = []    # 预测的工作集读写情况（0读1写）

        read_workingset, write_workingset, predict_data_set, predict_isWrite_set = beam_search_Nord(vxid, data, opt_type, order_num)

        record_workingset[vxid] = {}
        record_workingset[vxid]["DATA"] = predict_data_set
        record_workingset[vxid]["ISWRITE"] = predict_isWrite_set
        record_workingset[vxid]["READ"] = read_workingset
        record_workingset[vxid]["WRITE"] = write_workingset

        # 工作集由list转化为set类型（方便进行运算）
        readset = set()
        for item in read_workingset:
            if isinstance(item, list):
                readset.update(item)
            else:
                readset.add(item)
        writeset = set()
        for item in write_workingset:
            if isinstance(item, list):
                writeset.update(item)
            else:
                writeset.add(item)

        # 判断隔离级别
        for key in txn_workingset:
            if key != vxid:
                readset_temp = set(txn_workingset[key][0])
                writeset_temp = set(txn_workingset[key][1])

                inter_RW = readset.intersection(writeset_temp)
                inter_RR = readset.intersection(readset_temp)
                inter_WR = writeset.intersection(readset_temp)
                inter_WW = writeset.intersection(writeset_temp)

                if not rwPredict:
                    if inter_RW or inter_RR or inter_WR or inter_WW:
                        pre_isolevel_dict[vxid] = 3
                else:
                    if inter_RW or ((0 in readset) and (len(writeset_temp)!= 0)):
                        # 判断是否为严格定义，is_strict为0表示广义，非0表示严格
                        if (is_strict == 0):
                            if (vxid not in pre_isolevel_dict) or ((vxid in pre_isolevel_dict) and (pre_isolevel_dict[vxid] < 2)):
                                pre_isolevel_dict[vxid] = 2
                                # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 可能发生不可重复读或幻读")
                        else:
                            for x in inter_RW:
                                if read_workingset.count(x) >=2: # 在严格定义下，进一步检查读取某一数据的次数
                                    if (vxid not in pre_isolevel_dict) or ((vxid in pre_isolevel_dict) and (pre_isolevel_dict[vxid] < 2)):
                                        pre_isolevel_dict[vxid] = 2
                                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 可能发生不可重复读或幻读")

                    if inter_WR or ((0 in readset_temp) and (len(writeset)!= 0)):
                        # 判断是否为严格定义
                        if (is_strict == 0):
                            if (key not in pre_isolevel_dict) or ((key in pre_isolevel_dict) and (pre_isolevel_dict[key] < 2)):
                                pre_isolevel_dict[key] = 2
                                # print("事务" + str(key) + " 与 事务" + str(row["VXID"]) + " 可能发生不可重复读或幻读")
                        else:
                            for x in inter_WR:
                                if txn_workingset[key][0].count(x) >=2: # 在严格定义下，进一步检查读取某一数据的次数
                                    if (key not in pre_isolevel_dict) or ((key in pre_isolevel_dict) and (pre_isolevel_dict[key] < 2)):
                                        pre_isolevel_dict[key] = 2
                                        # print("事务" + str(key) + " 与 事务" + str(row["VXID"]) + " 可能发生不可重复读或幻读")

                    if inter_WW:
                        pre_isolevel_dict[vxid] = 3
                        pre_isolevel_dict[key] = 3
                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 可能发生丢失更新")

                    if inter_WR and inter_RW:
                        pre_isolevel_dict[vxid] = 3
                        pre_isolevel_dict[key] = 3
                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 可能发生写偏序异常")

        # 更新当前并发事务的工作集（读写工作集分开），并更新该事务上次读取到的数据项，为下次读取做准备
        txn_workingset[vxid] = {}
        txn_workingset[vxid][0] = read_workingset
        txn_workingset[vxid][1] = write_workingset

    # 对其他操作类型进行处理
    if type in ["COMMIT", "ROLLBACK"]:
        txn_workingset.pop(vxid)
        if vxid in count_vxid:
            count_vxid.pop(vxid)
        return

# 输入测试集，判断真实应推荐的隔离级别
real_txn_isolation = {}
def rec_real_txn_isolation(dataset, is_strict=0, is_2ord=0):
    global real_txn_isolation
    real_curr_workingset = {}
    for index, row in dataset.iterrows():
        vxid = row["VXID"]
        type = row["TYPE"]
        data = row["DATA"]

        if vxid not in real_txn_isolation:
            real_txn_isolation[vxid] = 1

        if vxid not in real_curr_workingset:
            real_curr_workingset[vxid] = {}
            real_curr_workingset[vxid]["READ"] = []
            real_curr_workingset[vxid]["WRITE"] = []

        # 对事务结束进行处理
        if type in ["COMMIT", "ROLLBACK"]:
            real_curr_workingset.pop(vxid)
            continue
        elif type not in ["SELECT", "UPDATE", "DELETE", "INSERT", ]:
            continue

        # 根据预测结果检查异象（预测异象）
        if data != -1:
            if type in ["SELECT"]:
                opt_type = 0  # 表示读操作
                real_curr_workingset[vxid]["READ"].append(data)
            elif type in ["UPDATE", "DELETE", "INSERT"]:
                opt_type = 1  # 表示写操作
                real_curr_workingset[vxid]["WRITE"].append(data)

            read_workingset = real_curr_workingset[vxid]["READ"]
            write_workingset = real_curr_workingset[vxid]["WRITE"]

            # 工作集由list转化为set类型（方便进行运算）
            readset = set(read_workingset)
            writeset = set(write_workingset)

            # 判断隔离级别
            for key in real_curr_workingset:
                if key != vxid:
                    readset_temp = set(real_curr_workingset[key]["READ"])
                    writeset_temp = set(real_curr_workingset[key]["WRITE"])

                    inter_RW = readset.intersection(writeset_temp)
                    inter_RR = readset.intersection(readset_temp)
                    inter_WR = writeset.intersection(readset_temp)
                    inter_WW = writeset.intersection(writeset_temp)

                    if inter_RW or ((0 in readset) and (len(writeset_temp)!= 0)):
                        # 判断是否为严格定义，is_strict为0表示广义，非0表示严格
                        if (is_strict == 0):
                            if real_txn_isolation[vxid] < 2:
                                real_txn_isolation[vxid] = 2
                                # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 实际发生不可重复读或幻读")
                        else:
                            for x in inter_RW:
                                if read_workingset.count(x) >=2: # 在严格定义下，进一步检查读取某一数据的次数
                                    if real_txn_isolation[vxid] < 2:
                                        real_txn_isolation[vxid] = 2
                                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 实际发生不可重复读或幻读")

                    if inter_WR or ((0 in readset_temp) and (len(writeset)!= 0)):
                        # 判断是否为严格定义
                        if (is_strict == 0):
                            if real_txn_isolation[key] < 2:
                                real_txn_isolation[key] = 2
                                # print("事务" + str(key) + " 与 事务" + str(row["VXID"]) + " 实际发生不可重复读或幻读")
                        else:
                            for x in inter_WR:
                                if real_curr_workingset[key]["READ"].count(x) >=2: # 在严格定义下，进一步检查读取某一数据的次数
                                    if real_txn_isolation[key] < 2:
                                        real_txn_isolation[key] = 2
                                        # print("事务" + str(key) + " 与 事务" + str(row["VXID"]) + " 实际发生不可重复读或幻读")

                    if inter_WW or (0 in writeset) or (0 in writeset_temp):
                        real_txn_isolation[vxid] = 3
                        real_txn_isolation[key] = 3
                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 实际发生丢失更新")

                    if inter_WR and inter_RW:
                        real_txn_isolation[vxid] = 3
                        real_txn_isolation[key] = 3
                        # print("事务" + str(row["VXID"]) + " 与 事务" + str(key) + " 实际发生写偏序异常")

def getIsolationLevel(isolation_int):
    if isolation_int <= 2:
        return "SSI"
    elif isolation_int == 3:
        return "PCCC"
    else:
        return "Unknown"


def testMarkov(dataset_train, dataset_test, order_num, rwPredict):
    global real_txn_isolation
    if(order_num >3):
        order_num = order_num - 3
    model_name = str(order_num) + "ord_model_" + log_directory
    if (rwPredict):
        save_to_file("./model/" + model_name + "_rw", data_item_dict)
    else:
        save_to_file("./model/" + model_name, data_item_dict)

    # 回滚事务
    rollback_txn = []

    # 真实应推荐的隔离级别
    real_txn_isolation = {}
    rec_real_txn_isolation(dataset_test)

    # for key in count_vxid:
    #     if (count_vxid[key] < 20):
    #         print("Transaction " + str(key) + " has " + str(count_vxid[key]) + " dataitems.")
    dict_vxid_hash = []
    for key in last_data_in_txn:
        hash_vxid = (int(str(key)[:str(key).index("/")]) * 7 + int(str(key)[str(key).index("/") + 1:]) * 11) % 100
        if hash_vxid not in dict_vxid_hash:
            dict_vxid_hash.append(hash_vxid)

    with open("C:\\Users\\Administrator\\Desktop\\data.txt", 'w') as f:
        i_count = 0
        for key in data_item_hash:
            i_count = i_count + 1
            if i_count != len(data_dict):
                f.write(str(data_item_hash[key]) + ":" + str(key) + "\n")
            else:
                f.write(str(data_item_hash[key]) + ":" + str(key))
        f.close()

    with open("C:\\Users\\Administrator\\Desktop\\matrix.txt", 'w') as f:
        for key in matrix_2ord:
            for keyy in matrix_2ord[key]:
                for keyyy in matrix_2ord[key][keyy]:
                    f.write(
                        str(key) + "," + str(keyy) + "," + str(keyyy) + ":" + str(matrix_2ord[key][keyy][keyyy]) + "\n")
        f.close()

    with open("C:\\Users\\Administrator\\Desktop\\write.txt", 'w') as f:
        i_count = 0
        for key in data_write_matrix_dict:
            i_count = i_count + 1
            if (i_count != len(data_write_matrix_dict)):
                f.write(str(key) + ":" + str(data_write_matrix_dict[key][0]) + "," + str(
                    data_write_matrix_dict[key][1]) + "\n")
            else:
                f.write(
                    str(key) + ":" + str(data_write_matrix_dict[key][0]) + "," + str(data_write_matrix_dict[key][1]))
        f.close()

    # 从上往下扫描，模拟事务的并发过程
    time3 = time.time()

    percent_test = 0
    already_predict = []
    for index, row in dataset_test.iterrows():
        if index > len(dataset_test) * percent_test:
            if (row["VXID"] not in pre_isolevel_dict):  # 若该事务不在隔离级别推荐列表中，说明是事务的第一步操作（非BEGIN）
                pre_isolevel_dict[row["VXID"]] = 1

            if row["TYPE"] in ["ROLLBACK"]:
                rollback_txn.append(row["VXID"])

            if (row["TYPE"] in ["COMMIT", "ROLLBACK"]) and (row["VXID"] in txn_workingset):
                txn_workingset.pop(row["VXID"])
                count_vxid.pop(row["VXID"])
                continue
            elif row["TYPE"] not in ["SELECT", "UPDATE", "DELETE", "INSERT"]:  # 只扫描DML和DQL
                continue

            if row["TYPE"] in ["SELECT"]:
                opt_type = 0
            else:
                opt_type = 1

            # 更新获取到的事务信息
            if row["VXID"] not in data_item_dict:
                empty_item = (-1, -1, -1)
                data_item_dict[row["VXID"]] = (row["DATA"], opt_type, empty_item, 1)  # 数据项，数据读写，上一项数据项，当前数据项数
            else:
                new_item = (row["DATA"], opt_type, data_item_dict[row["VXID"]], data_item_dict[row["VXID"]][3] + 1)
                data_item_dict[row["VXID"]] = new_item

            if row["VXID"] not in real_txn_workingset:
                real_txn_workingset[row["VXID"]] = {}
                real_txn_workingset[row["VXID"]][0] = []
                real_txn_workingset[row["VXID"]][1] = []
                real_txn_workingset[row["VXID"]][2] = []
            real_txn_workingset[row["VXID"]][opt_type].append(row["DATA"])
            real_txn_workingset[row["VXID"]][2].append(row["DATA"])

            if (row["VXID"] in already_predict):
                continue
            # print(str(row["TYPE"]+ " WHERE "+ row["STATEMENT"]))

            if data_item_dict[row["VXID"]][3] == order_num:
                rec_txn_isolation(row["VXID"], str(row["TYPE"] + " WHERE " + row["STATEMENT"]), test_is_strict, order_num, rwPredict)  # 倒数第二个参数：0表示广义，1表示严格；最后一个参数：0表示一阶马尔科夫，1表示二阶马尔科夫
            else:
                continue
            already_predict.append(row["VXID"])

    time4 = time.time()
    print("Total Time:")
    print(time4 - time3)

    # 计算事务总数
    count_train_txn = 0
    count_test_txn = 0

    for index, row in dataset_train.iterrows():
        if (row["TYPE"] in ["COMMIT", "ROLLBACK"]):
            count_train_txn = count_train_txn + 1

    for index, row in dataset_test.iterrows():
        if (row["TYPE"] in ["COMMIT", "ROLLBACK"]):
            count_test_txn = count_test_txn + 1

    # 比较准确率
    count_correct = 0
    count_more = 0
    count_less = 0
    for key in pre_isolevel_dict:
        if pre_isolevel_dict[key] == real_txn_isolation[key]:
            count_correct += 1
        elif (pre_isolevel_dict[key] > real_txn_isolation[key]) and (pre_isolevel_dict[key] == 3):
            count_more += 1
        elif (pre_isolevel_dict[key] < real_txn_isolation[key]) and (real_txn_isolation[key] == 3):
            count_less += 1
        else:
            count_correct += 1
    total = count_correct + count_more + count_less

    print("训练事务总数：" + str(count_train_txn))
    print("测试事务总数：" + str(count_test_txn))
    if(rwPredict):
        text_print = "有读写"
    else:
        text_print = "无读写"
    print("----- " + str(order_num) +"阶" + text_print + " -----")
    # print("准确数：" + str(count_correct))
    print("ACC：" + str(count_correct / total))
    # print("预测偏高：" + str(count_more))
    print("FPR：" + str(count_more / total))
    # print("预测偏低：" + str(count_less))
    print("FNR：" + str(count_less / total))


if __name__=="__main__":
    # 预处理日志文件（分别处理训练文件和测试文件）
    dataset_train = read_csv_data(log_train_file)
    dataset_test = read_csv_data(log_test_file)

    # 获取转移矩阵
    get_matrix_Nord(dataset_train)

    if conf_index == 1:
        testMarkov(dataset_train, dataset_test, 1, True)
    elif conf_index == 2:
        testMarkov(dataset_train, dataset_test, 2, True)
    elif conf_index == 3:
        testMarkov(dataset_train, dataset_test, 3, True)
    elif conf_index == 4:
        testMarkov(dataset_train, dataset_test, 1, False)
    elif conf_index == 5:
        testMarkov(dataset_train, dataset_test, 2, False)
    elif conf_index == 6:
        testMarkov(dataset_train, dataset_test, 3, False)