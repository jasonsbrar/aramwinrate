from riotwatcher import LolWatcher, ApiError
from api_key import key
from rate_limit import RateLimitRule, RateLimiter
import pandas as pd
import constants
import json, sys

watcher = LolWatcher(key)

rules = [RateLimitRule(20, 1), RateLimitRule(100, 120)]
limiter = RateLimiter(rules)

# account_id from username+region
def get_account_id(name, region):
    summoner_info = limiter.call(watcher.summoner.by_name, region, name)
    account_id = summoner_info['accountId']
    return account_id

# Returns list of game_ids corresponding to aram games played by this player
def get_aram_games_not_limited(account_id, region, begin, end):
    match_info = watcher.match.matchlist_by_account(region, account_id, queue=[constants.ARAM], begin_index=begin, end_index=end)
    match_list = match_info['matches']
    game_ids = [match['gameId'] for match in match_list]
    return game_ids
def get_aram_games(account_id, region, begin, end):
    return limiter.call(get_aram_games_not_limited, account_id, region, begin, end)

# Returns dict of {champion_key: champion_name}
def get_champ_dict(region):
    versions = limiter.call(watcher.data_dragon.versions_for_region, region)
    version = versions['n']['champion']
    champion_info = limiter.call(watcher.data_dragon.champions, version)
    champion_names = champion_info['data']
    champ_dict = {champ_entry['key']: champ_name for champ_name, champ_entry in champion_names.items()}
    return champ_dict

# Returns match from game_id
def get_match(game_id, region):
    return limiter.call(watcher.match.by_id, region, game_id)

# Returns (win: bool, champ_name: string) for whether player won or not
def get_match_info(match, account_id, champ_dict):
    # Get participant id from username
    participant_identities = match['participantIdentities']
    participant_id = next(participant['participantId'] for participant in participant_identities if participant['player']['accountId'] == account_id)
    # Get champ + win status from participant id
    participants_info = match['participants']
    participant_info = None
    for participant in participants_info:
        if participant['participantId'] == participant_id:
            participant_info = participant
    participant_info = next(participant for participant in participants_info if participant['participantId'] == participant_id)

    win = participant_info['stats']['win']
    champ_id = participant_info['championId']
    champ = champ_dict[str(champ_id)]
    return (win, champ)

# Returns list of (win: bool, champ_name: string) for a given player
def get_aram_history(account_id, region, champ_dict, batch_size=10):
    aram_history, aram_games = [], []
    aram_games_batch, start = [0], 0
    # Keep getting new batches while the previous batch was not empty
    while aram_games_batch != []:
        aram_games_batch = get_aram_games(account_id, region, start, start + batch_size)
        aram_games.extend(aram_games_batch)
        start += batch_size
    for game in aram_games:
        match = get_match(game, region)
        match_info = get_match_info(match, account_id, champ_dict)
        aram_history.append(match_info)
    return aram_history

# Returns dict of {champion: (win_count, games_played)} given aram history
def aggregate_aram_history(aram_history, champ_dict):
    champ_wl = {champ: (0, 0) for champ in champ_dict.values()}
    for win, champ in aram_history:
        win_count = champ_wl[champ][0] + win
        games_played = champ_wl[champ][1] + 1
        champ_wl[champ] = (win_count, games_played)
    return champ_wl

# Format aggregated history into pandas dataframe
def format_history(aggregated_history, username):
    rows = []
    total_wins, total_games = 0, 0
    # Calculate winrate for each champion
    for champ, entry in aggregated_history.items():
        win_count, games_played = entry
        winrate = win_count / max(1, games_played)
        winrate = round(100*winrate, 1)
        row = [champ, win_count, games_played, winrate]
        rows.append(row)
        total_wins += win_count
        total_games += games_played

    field_names = ['champion', 'wins', 'games played', 'winrate']
    overall_winrate = total_wins / max(1, total_games)
    overall_winrate = round(100*overall_winrate, 1)
    rows.append(['overall', total_wins, total_games, overall_winrate])
    df = pd.DataFrame(rows, columns=field_names)
    df.sort_values(by=['games played'], inplace=True, ascending=False)
    return df

# Writes data frame as csv
def write_csv(df, filename):
    df.to_csv('../data/' + filename, index=False)

def get_aram_winrates_dataframe(username: str, region: str) -> pd.DataFrame:
    """Returns winrates for each champ over specified number of games.

    Args:
        username (string): The username of the player to query
        region (string): The region of the given player

    Returns:
        pd.DataFrame: Contains [champion, wins, games played, winrate] for every champion
    """
    champ_dict = get_champ_dict(region)
    account_id = get_account_id(username, region)
    aram_history_list = get_aram_history(account_id, region, champ_dict)
    aggregated_history = aggregate_aram_history(aram_history_list, champ_dict)
    formatted_history = format_history(aggregated_history, username)
    return formatted_history

def get_aram_winrates(username: str, region: str) -> str:
    """Returns winrates for each champ over specified number of games.

    Args:
        username (string): The username of the player to query
        region (string): The region of the given player

    Returns:
        json object: Object is {champion: {total wins: n, games played: n, winrate: n}}
    """
    json_object = {} 
    df = get_aram_winrates_dataframe(username, region)
    for _, row in df.iterrows():
        champion = row['champion']
        wins = row['wins']
        games_played = row['games played']
        winrate = row['winrate']
        entry = {'wins': wins, 'games played': games_played, 'winrate': winrate}
        json_object[champion] = entry
    return json.dumps(json_object)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(sys.argv)
        print("Usage: python aram_winrate.py [username]")
        print("Only NA is supported via command line")
        exit(0)
    username = sys.argv[1]
    aram_winrates = get_aram_winrates_dataframe(username, constants.REGION_NA)
    write_csv(aram_winrates, username + '.csv')
