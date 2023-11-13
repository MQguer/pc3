import threading
import psycopg2
import random
import time

# Configs for PostgreSQL
myhost="127.0.0.1"          # host
mydb="postgres"             # database name
myrole="Administrator"      # user role name
mypwd=""                    # password

# Configs for chain waiting simulator
bool_chain          =   True        # whether to use chain waiting detection or not
DATABASE_SIZE       =   1000        # how many data items inserted into the database
TXN_SIZE            =   20          # how many operations inside each transaction
THREAD_NUM          =   100         # how many threads(transactions, one thread for one concurrent transaction)
ORDER_NUM           =   2           # which kind of markov (just for simulation, not very useful)

# Others
count_commit = 0                    # count the number of successfully committed transactions
count_rollback = 0                  # count the number of unsuccessfully committed transactions (due to update error or something else)
count_timeout = 0                   # count the number of timeout transactions (not counted into the previous two)

transaction_pool    =   {}          # concurrent transactions and their seeds
                                    # "seed" is the first data accesed by the transaction
                                    # we use the seed to represent different transactions in our simulator (similar to transaction ID)
waiting_txn         =   []          # all the transactions in waiting(sleeping)
to_wake_txn         =   []          # all the transactions to be waken
                                    # A transaction is removed from waiting_txn only under 2 circumstances:
                                    #    1. The transaction has been waiting for too long and reached the timeout limit (100 milliseconds in this simulator)
                                    #    2. It is added into to_wake_txn list, which means it no longer needs waiting

waiting_chain       =   {}          # The waiting chain (only records transactions that are waiting for other transactions)
waited_chain        =   {}          # The waited chain (only records transactions that are being waited by other transactions)

# 执行事务操作
# if seed == 0:
#     name_seed = "000"
# elif seed < 10:
#     name_seed = str(seed * 111)
# else:
#     name_seed = str(seed)
# insert_statement = "INSERT INTO test VALUES(" + str(seed) + ", " + name_seed + ")"

# With chain waiting detection simulation
def chain_waiting_detect_txn(conn, seed):
    global count_commit
    global count_rollback
    global count_timeout
    try:
        # 开始事务
        conn.autocommit = False
        cursor = conn.cursor()

        # 用seed来代替事务ID标记事务
        if(seed not in transaction_pool):
            transaction_pool[seed]  =   0

        # 每个事务操作的数据项是从seed开始的20（TXN_SIZE）个连续数据项
        for i in range(0, TXN_SIZE):
            id          =   seed % DATABASE_SIZE + i
            isWrite     =   1
            # 判断读写，为了模拟读写比例2:8，我们令 %10 == 0或1的数据项为读操作
            if i % 10 <= 1:
                isWrite     =   0

            # 以2阶马尔可夫为例，在读到第二个数据项时进行预测，因为这里只是模拟链式等待，所以简化了预测的过程
            if i == ORDER_NUM - 1:
                for key in transaction_pool:
                    if key != seed and key <= seed + TXN_SIZE - 1 and key + TXN_SIZE - 1 >= seed: # 每个事务操作的数据项是连续的TXN_SIZE个数据项，据此我们简化了预测过程
                        transaction_pool[seed] = max(transaction_pool[seed], transaction_pool[key]+1)
                        if key not in waiting_txn:
                            if seed not in waiting_chain:
                                waiting_chain[seed] = []
                            if key not in waiting_chain[seed]:
                                waiting_chain[seed].append(key)
                            if key not in waited_chain:
                                waited_chain[key] = []
                            if seed not in waited_chain[key]:
                                waited_chain[key].append(seed)

                if (transaction_pool[seed] %2 == 1):
                    waiting_txn.append(seed)
                    count = 0
                    while (seed not in to_wake_txn):
                        time.sleep(0.02)
                        count = count + 1
                        if count >= 5:
                            print("waiting for too long:" + str(seed))
                            count_timeout   =   count_timeout + 1
                            count_commit    =   count_commit - 1
                            break
                    waiting_txn.remove(seed)
                else:
                    if seed in waiting_chain:
                        for data in waiting_chain[seed]:
                            if (transaction_pool[seed] % 2 == 1):
                                if data in waited_chain:
                                    if seed in waited_chain[data]:
                                        waited_chain[data].remove(seed)
                                if seed in waited_chain:
                                    if data not in waited_chain[seed]:
                                        waited_chain[seed].append(data)
                                else:
                                    waited_chain[seed] = []
                                    waited_chain[seed].append(data)

            # transaction_pool[seed]["workset"].append(id)
            # transaction_pool[seed]["rwset"].append(isWrite)

            if isWrite == 0:
                statement = "SELECT * from test where id = " + str(id)
            else:
                statement = "UPDATE test SET name =" + str(id) + " WHERE id = " + str(id)
            cursor.execute(statement)

        # 提交事务
        if seed in waited_chain:
            for data in waited_chain[seed]:
                if seed in waiting_chain[data]:
                    waiting_chain[data].remove(seed)
                if len(waiting_chain[data]) == 0:
                    if data in waiting_txn:
                        to_wake_txn.append(data)
            del waited_chain[seed]
        if seed in transaction_pool:
            del transaction_pool[seed]
        conn.commit()
        count_commit = count_commit + 1
        print("Transaction committed successfully, seed = " + str(seed))
    except (Exception, psycopg2.DatabaseError) as error:
        # 回滚事务
        if seed in waited_chain:
            for data in waited_chain[seed]:
                if seed in waiting_chain[data]:
                    waiting_chain[data].remove(seed)
                if len(waiting_chain[data]) == 0:
                    if data in waiting_txn:
                        to_wake_txn.append(data)
            del waited_chain[seed]
        if seed in transaction_pool:
            del transaction_pool[seed]
        conn.rollback()
        count_rollback = count_rollback + 1
        print("Transaction rolled back due to error:", error)
    finally:
        # 关闭数据库连接
        cursor.close()
        conn.close()


# Without chain waiting detection simulation
def non_chain_waiting_detect_txn(conn, seed):
    global count_commit
    global count_rollback
    global count_timeout
    try:
        # 开始事务
        conn.autocommit = False
        cursor = conn.cursor()

        # 用seed来代替事务ID标记事务
        if (seed not in transaction_pool):
            transaction_pool[seed] = 0

        # 每个事务操作的数据项是从seed开始的20（TXN_SIZE）个连续数据项
        for i in range(0, TXN_SIZE):
            id = seed % DATABASE_SIZE + i
            isWrite = 1
            # 判断读写，为了模拟读写比例2:8，我们令 %10 == 0或1的数据项为读操作
            if i % 10 <= 1:
                isWrite = 0

            # 以2阶马尔可夫为例，在读到第二个数据项时进行预测，因为这里只是模拟链式等待，所以简化了预测的过程
            if i == ORDER_NUM - 1:
                for key in transaction_pool:
                    if key != seed and key <= seed + TXN_SIZE - 1 and key + TXN_SIZE - 1 >= seed:  # 每个事务操作的数据项是连续的TXN_SIZE个数据项，据此我们简化了预测过程
                        transaction_pool[seed] = max(transaction_pool[seed], transaction_pool[key] + 1)
                        if key not in waiting_txn:
                            if seed not in waiting_chain:
                                waiting_chain[seed] = []
                            if key not in waiting_chain[seed]:
                                waiting_chain[seed].append(key)
                            if key not in waited_chain:
                                waited_chain[key] = []
                            if seed not in waited_chain[key]:
                                waited_chain[key].append(seed)
                if (seed in waiting_chain):
                    waiting_txn.append(seed)
                    count = 0
                    while (seed not in to_wake_txn):
                        time.sleep(0.02)
                        count = count + 1
                        if count >= 5:
                            print("waiting for too long:" + str(seed))
                            count_commit = count_commit - 1
                            count_timeout = count_timeout + 1
                            break
                    waiting_txn.remove(seed)

            # transaction_pool[seed]["workset"].append(id)
            # transaction_pool[seed]["rwset"].append(isWrite)

            if isWrite == 0:
                statement = "SELECT * from test where id = " + str(id)
            else:
                statement = "UPDATE test SET name =" + str(id) + " WHERE id = " + str(id)
            cursor.execute(statement)

        # 提交事务
        if seed in waited_chain:
            for data in waited_chain[seed]:
                if data in waiting_chain:
                    if seed in waiting_chain[data]:
                        waiting_chain[data].remove(seed)
                    if len(waiting_chain[data]) == 0:
                        if data in waiting_txn:
                            to_wake_txn.append(data)
            del waited_chain[seed]
        if seed in waiting_chain:
            del waiting_chain[seed]
        if seed in transaction_pool:
            del transaction_pool[seed]
        conn.commit()
        count_commit = count_commit + 1
        print("Transaction committed successfully, seed = " + str(seed))
    except (Exception, psycopg2.DatabaseError) as error:
        # 回滚事务
        if seed in waited_chain:
            for data in waited_chain[seed]:
                if data in waiting_chain:
                    if seed in waiting_chain[data]:
                        waiting_chain[data].remove(seed)
                    if len(waiting_chain[data]) == 0:
                        if data in waiting_txn:
                            to_wake_txn.append(data)
            del waited_chain[seed]
        if seed in waiting_chain:
            del waiting_chain[seed]
        if seed in transaction_pool:
            del transaction_pool[seed]
        conn.rollback()
        count_rollback = count_rollback + 1
        print("Transaction rolled back due to error:", error)
    finally:
        # 关闭数据库连接
        cursor.close()
        conn.close()


# 并发执行事务
def concurrent_transactions():
    try:
        # Connect to PostgreSQL
        threads      =   []

        for i in range(0, THREAD_NUM):
            temp_conn = psycopg2.connect(
                host=myhost,
                database=mydb,
                user=myrole,
                password=mypwd
            )
            id = random.randint(0, 999)
            if not bool_chain:
                temp_thread = threading.Thread(target=non_chain_waiting_detect_txn, args=(temp_conn, id))
            else:
                temp_thread = threading.Thread(target=chain_waiting_detect_txn, args=(temp_conn, id))
            threads.append(temp_thread)

        time1 = time.time()
        for j in range(0, THREAD_NUM):
            threads[j].start()

        for k in range(0, THREAD_NUM):
            threads[k].join()
        time2 = time.time()
        print("Excution Time：" + str(time2 - time1))
        print("Commit Transactions：" + str(count_commit))
        print("Error Transactions：" + str(count_rollback))
        print("Timeout Transactions：" + str(count_timeout))

    except (Exception, psycopg2.DatabaseError) as error:
        print("Error connecting to PostgreSQL:", error)

# 调用并发执行事务函数
concurrent_transactions()