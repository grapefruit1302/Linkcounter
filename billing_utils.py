from colorama import Fore, Style

def add_TD(start_time, region, host, notes):
    print(Fore.GREEN + "add TD")
    print("start_time: ", start_time)
    print("region: ", region)
    print("host: ", host)
    print("notes:", notes)
    print(Style.RESET_ALL)

    #region:
    #TE - Ternopil
    #TEO - Ternopil region
    #CG - Chervonograd
    #VV - Volodimyr

def close_TD(solution_time, region, host):
    print(Fore.GREEN + "close TD")
    print("solution_time: ", solution_time)
    print("region: ", region)
    print("host: ", host)
    print(Style.RESET_ALL)
