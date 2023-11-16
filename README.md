# PC3
Here are the codes for the Prior Cascading Concurrency Control (PC^{3}) Method in PostgreSQL.



There are 4 parts of the project:

**1. Markov**: 
   This is a Python program to analyse logs from PostgreSQL and generate relative data about Markov Transition Matrix. This program can also test the accuracy, FPR and FNR of the Markov Prediction Algorithm.

**2. PGSource**: 
   This is the source code of PostgreSQL 13.9 after our modification. We add simulative codes about 2PL, SSN and our PC3 in the project. We add the options in GUC so that users can change the CC strategy through `SET` command or in the .conf file after installing PostgreSQL.

**3. PGInstalled**: 
   This is a installed version of the PGSource, just in case that some errors may occur during installing. There is also our modified .conf file in the "./data" directory, in which we can change the CC strategy and default isolation level of PostgreSQL. You need to restart the PG server with `pg_ctl` command every time when you change the .conf file.

**4. YCSB**: 
    This is a modifies version of YCSB 0.15.0. We changed the seed in JDBC codes so that every time we run YCSB, it will generate the same series of transactions (but different in executing orders). This is of convenience for us to use database logs to train the transition matrix and make accurate predictions.
