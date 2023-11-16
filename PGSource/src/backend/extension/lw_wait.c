/*-------------------------------------------------------------------------
 *
 * lw_wait.c
 *	  Light-weighted auto-wait functions for concurrent transactions.
 *
 * Portions Copyright (c) 
 * Portions Copyright (c) 
 *
 *
 * IDENTIFICATION
 *	  src/backend/extension/lw_wait.c
 
 * NOTES
 *	  this is an extension which does not belong to the original PostgreSQL source codes.
 *	  this file is an extension to add transaction-auto-wait function into PG.
 *	  we can automatically predict whether two concurrent transactions may conflict 
 *	  with each other, and then we can pause one of the transactions to make the 
 *	  other transaction commit successfully.
 *
 *-------------------------------------------------------------------------
 */

#include "postgres.h"
 
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <ctype.h>
#include <stdbool.h>
#include <unistd.h>
#include <sys/socket.h>
#ifdef HAVE_SYS_SELECT_H
#include <sys/select.h>
#endif
#ifdef HAVE_SYS_RESOURCE_H
#include <sys/time.h>
#include <sys/resource.h>
#endif
#ifndef HAVE_GETRUSAGE
#include "rusagestub.h"
#endif
#include "access/parallel.h"
#include "access/printtup.h"
#include "access/xact.h"
#include "catalog/pg_type.h"
#include "commands/async.h"
#include "commands/prepare.h"
#include "jit/jit.h"
#include "libpq/libpq.h"
#include "libpq/pqformat.h"
#include "libpq/pqsignal.h"
#include "mb/pg_wchar.h"
#include "mb/stringinfo_mb.h"
#include "miscadmin.h"
#include "nodes/print.h"
#include "optimizer/optimizer.h"
#include "parser/analyze.h"
#include "parser/parser.h"
#include "pg_getopt.h"
#include "pg_trace.h"
#include "pgstat.h"
#include "postmaster/autovacuum.h"
#include "postmaster/interrupt.h"
#include "postmaster/postmaster.h"
#include "replication/logicallauncher.h"
#include "replication/logicalworker.h"
#include "replication/slot.h"
#include "replication/walsender.h"
#include "rewrite/rewriteHandler.h"
#include "storage/bufmgr.h"
#include "storage/ipc.h"
#include "storage/proc.h"
#include "storage/procsignal.h"
#include "storage/procarray.h"
#include "storage/sinval.h"
#include "tcop/fastpath.h"
#include "tcop/pquery.h"
#include "tcop/tcopprot.h"
#include "tcop/utility.h"
#include "utils/lsyscache.h"
#include "utils/memutils.h"
#include "utils/ps_status.h"
#include "utils/snapmgr.h"
#include "utils/timeout.h"
#include "utils/timestamp.h"

/**************************************************

extern VirtualTransactionId GetVirtualXid(void);


void createAndWriteFile(const char *content, const char *directory, const char *filename)
{
    char filepath[256];
    snprintf(filepath, sizeof(filepath), "%s\\%s", directory, filename);

    FILE *file = fopen(filepath, "a");
    if(file == NULL)
    {
        printf("Failed to create file: %s\n", filepath);
        return;
    }

    fputs(content, file);
    fclose(file);
}

char* 
concatenateStrings(const char* str1, const char* str2) {
    size_t len1 = strlen(str1);
    size_t len2 = strlen(str2);
    size_t resultLen = len1 + len2 + 1; 

    char* result = (char*)malloc(resultLen);
    if(result == NULL) {
        fprintf(stderr, "Failed to allocate memory\n");
        return NULL;
    }

    strcpy(result, str1);  
    strcat(result, str2);

    return result;
}


bool 
containsSubstring(const char* str, const char* substring) 
{
    return strstr(str, substring) != NULL;
}


char* removeNewlines(const char *str) {
    int len = strlen(str);
    int i = 0;
    int j = 0;
    char *result = (char *)malloc((len + 1) * sizeof(char)); 

    for (i = 0; i < len; i++) {
        if (str[i] != '\n') {
            result[j] = str[i];
            j++;
        }
    }

    result[j] = '\0';

    return result; 
}


char* 
removeSpecialChars(const char *str) {
    int len = strlen(str);
    int i = 0;
    int j = 0;
    char *result = (char *)malloc((len + 1) * sizeof(char)); 

    for (i = 0; i < len; i++) {
        if (str[i] != '\n' && str[i] != '\'' && str[i] != '\"') {
            result[j] = str[i];
            j++;
        }
    }

    result[j] = '\0';

    return result; 
}


const char* replaceSingleQuotes(const char* str) {
    size_t len = strlen(str);
    char* result = (char*)malloc((len * 3) + 1);
    if (result == NULL) {
        fprintf(stderr, "Failed to allocate memory\n");
        return NULL;
    }
    size_t resultIdx = 0;
    size_t i = 0;
    for (i = 0; i < len; i++) {
        if (str[i] == '\'') {
            result[resultIdx++] = '\\';
            result[resultIdx++] = '\\';
            result[resultIdx++] = '\\';
            result[resultIdx++] = '\'';
        } else {
            result[resultIdx++] = str[i];
        }
    }
    return result;
}


char* intToString(int value) 
{
    char* result = NULL;
    int size = snprintf(NULL, 0, "%d", value); 
    if (size > 0) 
	{
        result = (char*) malloc((size + 1) * sizeof(char));
        if (result != NULL) 
            snprintf(result, size + 1, "%d", value); 
    }
    
    return result;
}


char* boolToString(bool value) 
{
    return value?"True":"False";
}


char* pointerToString(const void* ptr) 
{
    char* result = NULL;
    int size = snprintf(NULL, 0, "%p", ptr);
    
    if (size > 0) 
	{
        result = (char*) malloc((size + 1) * sizeof(char)); 
        if (result != NULL)
            snprintf(result, size + 1, "%p", ptr);
    }
    
    return result;
}

char* exec_my_command(const char* command)
{
	char buffer[BUFFER_SIZE];
	char* result = "";
	
    FILE* pipe = popen(command, "r");
    if(!pipe) 
	{
        printf("Failed to execute command\n");
        return result;
    }
	
    
    while(fgets(buffer, BUFFER_SIZE, pipe) != NULL) {
        result = removeNewlines(concatenateStrings(result, buffer));
    }
	
    pclose(pipe);
    
    return result;
}


char* convertVirtualTransactionIdToString(VirtualTransactionId vxid)
{
	char* result = malloc(20);
	snprintf(result, 20, "%u/%u", vxid.backendId, vxid.localTransactionId);
	return result;
}

const char* 
getSqlStatementType(const char* query_string_sql) {
	const char* sql = query_string_sql;
	while (isspace(*sql)) {
		sql++;
	}

	int firstWordLength = 0;
	while (isalpha(sql[firstWordLength])) {
		firstWordLength++;
	}

	char* firstWord = (char*)malloc(firstWordLength + 1); 
	if (firstWord == NULL) {
		return NULL;
	}

	strncpy(firstWord, sql, firstWordLength);
	firstWord[firstWordLength] = '\0'; 

    for (int i = 0; firstWord[i]; i++) {
        firstWord[i] = toupper(firstWord[i]);
    }

    if (strcmp(firstWord, "SELECT") == 0) {
        return "SELECT";
    } else if (strcmp(firstWord, "UPDATE") == 0) {
        return "UPDATE";
    } else if (strcmp(firstWord, "INSERT") == 0) {
        return "INSERT";
    } else if (strcmp(firstWord, "DELETE") == 0) {
        return "DELETE";
    } else if (strcmp(firstWord, "BEGIN") == 0 || strcmp(firstWord, "START") == 0) {
        return "BEGIN";
    } else if (strcmp(firstWord, "COMMIT") == 0 || strcmp(firstWord, "END") == 0) {
        return "COMMIT";
    } else if (strcmp(firstWord, "ROLLBACK") == 0 || strcmp(firstWord, "ABORT") == 0) {
        return "ROLLBACK";
    } else {
        return "OTHERS";
    }
}




void lw_wait(const char* query_string, VirtualTransactionId current_vxid)
{
	const char *p = query_string;
	const char *query_type = getSqlStatementType(query_string);

	const char *destop = "C:\\Users\\Administrator\\Desktop\\OUTPUT";
	const char *filename1 = "example.txt";
	const char *filename2 = "example2.txt";
	const char *filename3 = "example3.txt";
	const char *changeline = "\n------\n";
	
	if(strcmp(query_type, "OTHERS")!=0 && strcmp(query_type, "BEGIN")!=0 && strcmp(query_type, "INSERT")!=0)
	{
		const char* vxid_str = convertVirtualTransactionIdToString(current_vxid);
		
		createAndWriteFile(vxid_str, destop, filename1);
		createAndWriteFile("  ", destop, filename1);
		createAndWriteFile(query_string, destop, filename1);
		createAndWriteFile(changeline, destop, filename1);
		
		const char* command1 = "python -c \"import Markov as m; m.rec_txn_isolation(\'"; 
		const char* command2 = "\',\'";
		const char* command3 = "')\"";
			
		const char* command = concatenateStrings(command1, vxid_str);
		command = concatenateStrings(command, command2);
		command = concatenateStrings(command, removeSpecialChars(query_string));
		command = concatenateStrings(command, command3);

		char* result = exec_my_command(command); 

		createAndWriteFile("WAITING: ", destop, filename3);
		createAndWriteFile(vxid_str, destop, filename3);
		createAndWriteFile("\n", destop, filename3);
		createAndWriteFile("RESULT: ", destop, filename3);
		createAndWriteFile(result, destop, filename3);
		createAndWriteFile(changeline, destop, filename3);

		PGPROC *proc = NULL;
		proc = BackendPidGetProc(MyProcPid);
	
		if(strcmp(query_type, "COMMIT")==0 || strcmp(query_type, "ROLLBACK")==0)
		{		
	
			createAndWriteFile("PID: ", destop, filename2);
			createAndWriteFile(intToString(MyProcPid), destop, filename2);
			createAndWriteFile("\nSharedData: ", destop, filename2);
			createAndWriteFile(pointerToString(SharedData), destop, filename2);
			createAndWriteFile("\n	Count_VXID: ", destop, filename2);
			createAndWriteFile(intToString(SharedData->count_vxid), destop, filename2);
			if(SharedData->count_vxid >= 1)
			{	
				int k = 0;
				for(k = 0; k < SharedData->count_vxid; k++)
				{
					createAndWriteFile("\n	VXID[ ", destop, filename2);
					createAndWriteFile(intToString(k), destop, filename2);
					createAndWriteFile("]: ", destop, filename2);
					createAndWriteFile(convertVirtualTransactionIdToString(SharedData->vxids[k]), destop, filename2);
				}
				createAndWriteFile(changeline, destop, filename2);
			}
			
			int j = 0, count = 0, index = -1;
			int count_waited_vxid = countSharedVXID(current_vxid);
			for(j = 0; j < count_waited_vxid; j++)
			{
				index = findSharedVXIDIndex(current_vxid, index+1);
				if(index != -1)
				{
					count = countSharedPid(SharedData->pids[index]);
					if(count <= 1)
					{
						proc = BackendPidGetProc(SharedData->pids[index]);
						SetLatch(&proc->procLatch);
						removeSharedVxid(current_vxid);
						
						createAndWriteFile("Set Latch: ", destop, filename2);
						createAndWriteFile(pointerToString(&proc->procLatch), destop, filename2);
						createAndWriteFile(changeline, destop, filename2);
					}
					else
						removeSharedVxid(current_vxid);
				}
			}
			
		}
		else
		{			
			if(!containsSubstring(result, "SI") && result[0] != '\0')
			{
				bool needsWaiting = true;
			
				const char* delimiter = "|";
				char* nextToken = NULL;

				while ((nextToken = strstr(result, delimiter)) != NULL)
				{
					*nextToken = '\0';
					VirtualTransactionId vxid = parseVirtualTransactionId(result);
					addSharedVXID(vxid, MyProcPid);
					result = nextToken + 1;
					if(!checkWaitingStatus(vxid))
					{
						needsWaiting = false;
					}
				}
				
				createAndWriteFile("PID: ", destop, filename2);
				createAndWriteFile(intToString(MyProcPid), destop, filename2);
				createAndWriteFile("\nSharedData: ", destop, filename2);
				createAndWriteFile(pointerToString(SharedData), destop, filename2);
				createAndWriteFile("\n	Count_VXID: ", destop, filename2);
				createAndWriteFile(intToString(SharedData->count_vxid), destop, filename2);

				if(SharedData->count_vxid >= 1)
				{
					int m = 0;
					for(m = 0; m < SharedData->count_vxid; m++)
					{
						createAndWriteFile("\n	VXID[ ", destop, filename2);
						createAndWriteFile(intToString(m), destop, filename2);
						createAndWriteFile("]: ", destop, filename2);
						createAndWriteFile(convertVirtualTransactionIdToString(SharedData->vxids[m]), destop, filename2);
					}
					createAndWriteFile(changeline, destop, filename2);
				}
				
				if(needsWaiting)
				{
					addWaitingVXID(current_vxid);
					ProcWaitForSharedSignal(PG_WAIT_SHARE);
				}
				
			}
		}
	}
	
}
*/

