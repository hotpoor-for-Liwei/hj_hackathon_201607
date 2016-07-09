#!/usr/bin/env python
# -*- coding: utf8 -*-

# try:
#     from tornado import database
# except:
#     import torndb as database

# conn = database.Connection("127.0.0.1", "test", "root", "root")
# conn1 = database.Connection("127.0.0.1", "test", "root", "root")
# conn2 = database.Connection("127.0.0.1", "test", "root", "root")
# conn3 = database.Connection("127.0.0.1", "test", "root", "root")

# ring = [conn1, conn2, conn3]

# import torndb as database
# conn = database.Connection("127.0.0.1", "hotpoor", "root", "root")
# conn1 = database.Connection("127.0.0.1", "hotpoor1", "root", "root")
# conn2 = database.Connection("127.0.0.1", "hotpoor2", "root", "root")
# ring = [conn1, conn2]

try:
    import torndb as database
    conn = database.Connection("127.0.0.1", "hotpoor", "root", "root")
    conn1 = database.Connection("127.0.0.1", "hotpoor1", "root", "root")
    conn2 = database.Connection("127.0.0.1", "hotpoor2", "root", "root")
    ring = [conn1, conn2]
    # conn = database.Connection("123.58.137.85", "hotpoor", "root", "hotpoorinchina")
    # conn1 = database.Connection("123.58.137.85", "hotpoor1", "root", "hotpoorinchina")
    # conn2 = database.Connection("123.58.137.85", "hotpoor2", "root", "hotpoorinchina")
    # conn3 = database.Connection("127.0.0.1", "hotpoor3", "root", "root")
    # conn4 = database.Connection("127.0.0.1", "hotpoor4", "root", "root")
    # ring = [conn1, conn2, conn3, conn4] # I love the name Ring

    #import redis
    #mem = redis.Redis(host='127.0.0.1', port=6379, db=0)
except:
    pass
