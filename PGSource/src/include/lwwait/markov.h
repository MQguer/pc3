

/*-------------------------------------------------------------------------
 *
 * markov.h
 *
 * src/include/lwwait/markov.h
 *
 *-------------------------------------------------------------------------*/

#ifndef MARKOV_H
#define MARKOV_H

#include <unistd.h>
#include <time.h>

#include "storage/lock.h"

/*
typedef struct HashTableNode{
    int key;	
    int val;		
    UT_hash_handle hh;
} HashTableNode;
*/

/*
typedef struct MySharedData
{
	VirtualTransactionId*	waitingVxids;
	VirtualTransactionId*	vxids;
	int*					pids;
	
	volatile int count_wait;
	volatile int count_vxid;
	volatile int count_pid;
} MySharedData;
*/

/* ------------- About EWL ------------- */

typedef struct WaitedNode
{
	VirtualTransactionId 		vxid;
	int							pid;
	VirtualTransactionId		source_vxid;
	bool						isTheLast;
} WaitedNode;

typedef struct WaitingNode
{
	VirtualTransactionId		vxid;
	VirtualTransactionId		destination_vxid;
	bool						isTheLast;
} WaitingNode; 


typedef struct PidCountNode
{
	int 	pid;
	int		count;
}PidCountNode;


typedef struct MySharedData
{
	WaitedNode*				waited_Vxids[TXN_SIZE];
	WaitingNode*			waiting_Vxids[TXN_SIZE];
	PidCountNode*			pid_waited[TXN_SIZE];

	VirtualTransactionId	sleeping_Vxids[TXN_SIZE];

	int 					conflict_num;
	
	LWLock					waited_writeLock;
	LWLock					waiting_writeLock;
	LWLock					pid_writeLock;
	LWLock					sleep_writeLock;
} MySharedData;

typedef struct DataItem {
    int 	data_content[DATAITEM_SIZE];
} DataItem;


typedef struct MarkovNode {
    int 				data1;
    int 				data2;
    int 				data3;
    int 				weight;
	bool				isTheLast;
    struct MarkovNode* 	next;
} MarkovNode;


typedef struct DataMatrix {
	MarkovNode* 	matrix[HASH_SIZE];
} DataMatrix;


typedef struct WriteNode {
	int 					data;
	int 					count_read;
	int 					count_write;
	struct WriteNode* 		next;
} WriteNode;


typedef struct WriteMatrix {
	WriteNode* 	matrix[HASH_SIZE];
} WriteMatrix;


typedef struct TransactionWorkingSet{
	VirtualTransactionId 						vxid;			
	int* 										workingset;
	int* 										isWrite;
	int 										count_data;
	bool										committed;
	time_t										begin_time;
	time_t										commit_time;
	struct 		TransactionWorkingSet*	 		next;
} TransactionWorkingSet;

typedef struct TransactionPool{
	TransactionWorkingSet*		headNode;
	TransactionWorkingSet*		workingSet[TXN_SIZE];
	LWLock						lock;
} TransactionPool;

typedef struct HashTableNode{
    int 			data;
    int	 			isWrite;
} HashTableNode;



/* ------------- About SSN ------------- */
typedef enum ConflictType
{
	Conf_WR,
	Conf_WW,					
	Conf_RW				
} ConflictType;

typedef struct InConflictRecord{
	VirtualTransactionId		source_vxid;
	ConflictType				type;
}InConflictRecord;


typedef struct OutConflictRecord{
	VirtualTransactionId		destination_vxid;
	ConflictType				type;
}OutConflictRecord;


typedef struct ConflictRecord{
	int						inCount;
	int						outCount;
	InConflictRecord		inConflicts[CONFLICT_SIZE];
	OutConflictRecord		outConflicts[CONFLICT_SIZE];
	time_t					maxInTime; 
	time_t					minOutTime;
}ConflictRecord;

typedef struct CommitTxn{
	VirtualTransactionId	vxid;
	bool					committed;
	time_t  				commitTime;
	ConflictRecord*			conflicts;
}CommitTxn;

typedef struct CommitTxnPool{
	CommitTxn* commitTxn[TXN_SIZE];
	LWLock	writeLock;
}CommitTxnPool;


/*  */
extern 	HashTableNode* initHashTable(HashTableNode* hashTable, int hashSize);
extern	void insertIntoHashTable(HashTableNode* hashTable, int hashSize, int data, int isWrite);
extern	bool findHashByData(HashTableNode* hashTable, int hashSize, int data, int isWrite);
extern	bool intersectNotEmpty(int* num1, int* isWrite1, int num1Size, int* num2, int* isWrite2, int num2Size);

/* About transactions */
extern bool equalVXID(VirtualTransactionId vxid1, VirtualTransactionId vxid2);

	
/*
extern HashTableNode* findKeyByHash(HashTableNode* hashTable, int ikey);
extern int* getIntersect(int* nums1, int nums1Size, int* nums2, int nums2Size, int* returnSize);
*/

#endif							/* MARKOV_H */
