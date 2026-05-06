# FCS_Renamer

Rename the $FIL field in FCS file headers for Flowjo  

If you are looking for a tools like [FCS-Renamer](https://www.cytometry.uzh.ch/en/Data-Services/FCS-Renamer.html), you get it here.   
`fcs_renamer.py` is simple python script to rename you FCS files. It can help you rename $FIL with original file name or provided filename mapping in csv.   

## FCS Renamer — Usage  
`fcs_renamer.py` No dependencies — pure Python stdlib only.    
### Mode 1: Rename $FIL to filename (default)    
1. Process all ".fcs" files in a folder (in-place)  
```  
python fcs_renamer.py /path/to/fcs/folder  
```  
2. For Single file
```  
python fcs_renamer.py sample.fcs
```
3. Write copies to a new folder instead of overwriting  
```
python fcs_renamer.py /path/to/fcs/folder --output /path/to/output
```  
### Mode 2: Rename using a CSV mapping  
```
python fcs_renamer.py /path/to/fcs/folder --csv mapping.csv  
```
CSV format (header row required):  
filename,new_name  
sample01.fcs,Patient_001_T0  
sample02.fcs,Patient_001_T1  
Note: Files not listed in the CSV are skipped automatically.   

### Dry-run (preview without writing)  
```
bashpython fcs_renamer.py /path/to/fcs/folder --dry-run  
```

### How it works  
The script directly edits the FCS TEXT segment in binary:  
  
Reads the 256-byte header to locate text_start / text_end offsets  
Parses key-value pairs using the segment's own delimiter character  
Replaces (or inserts) the $FIL keyword  
If the TEXT segment changes size, all affected header offsets are patched accordingly  
Works with FCS 2.0, 3.0, and 3.1 files — no third-party libraries needed  
