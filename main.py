import psutil 

def get_pids_for_pipe(pipe_path):                                         
      pids = []   
      for proc in psutil.process_iter():
          try:
              for f in proc.open_files():
                  if f.path == pipe_path:
                      pids.append(proc.pid)
                      break
          except (psutil.NoSuchProcess, psutil.AccessDenied):
              pass
      return pids

def main():

    pass


if __name__ == "__main__":
    main()
