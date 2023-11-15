# pc3
Here are codes of the Prior Cascading Concurrency Control(PC3) Method in PostgreSQL.

There are 3 parts of the project:

**1. Markov**: 
   This is a Python program to analyse logs from PostgreSQL and generate relative data about Markov Transition Matrix. This program can also test the accuracy, FPR and FNR of the Markov Prediction Algorithm.
   
**2. PGSource**: 
   This is the source code of PostgreSQL 13.9 after our modification. We add simulative codes about 2PL, SSN and our PC3 in the project. Users can change the mode (along with transaction isolation level) in the .conf file of PostgreSQL(PGDATA).
   
**3. PGInstalled**: 
   This is a installed version of the PGSource, just in case that some errors may occur during installing. There is also our modified .conf file in the "./data" directory, in which we can change the mode and isolation level of PostgreSQL. You need to restart the PG server every time when you change the .conf file.
   
