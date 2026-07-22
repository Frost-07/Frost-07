import datetime
from dateutil import relativedelta
import requests
import os
import io
from PIL import Image
from lxml import etree
import time
import hashlib

HEADERS = {'authorization': 'token '+ os.environ['ACCESS_TOKEN']}
USER_NAME = 'Frost-07'
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0}

def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return '{} {}, {} {}, {} {}{}'.format(
        diff.years, 'year' + format_plural(diff.years), 
        diff.months, 'month' + format_plural(diff.months), 
        diff.days, 'day' + format_plural(diff.days),
        ' 🎂' if (diff.months == 0 and diff.days == 0) else '')

def format_plural(unit): return 's' if unit != 1 else ''

def simple_request(func_name, query, variables):
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS)
    if request.status_code == 200: return request
    raise Exception(func_name, ' has failed with a', request.status_code, request.text, QUERY_COUNT)

def graph_commits(start_date, end_date):
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }'''
    variables = {'start_date': start_date,'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])

def graph_repos_stars(count_type, owner_affiliation, cursor=None, add_loc=0, del_loc=0):
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if request.status_code == 200:
        if count_type == 'repos':
            return request.json()['data']['user']['repositories']['totalCount']
        elif count_type == 'stars':
            return stars_counter(request.json()['data']['user']['repositories']['edges'])

def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS)
    if request.status_code == 200:
        if request.json()['data']['repository']['defaultBranchRef'] != None:
            return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
        else: return 0
    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception("Too many requests! You've hit the anti-abuse limit!")
    raise Exception('recursive_loc() has failed with a', request.status_code, request.text, QUERY_COUNT)

def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    for node in history['edges']:
        if node['node']['author']['user'] == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    else: return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])

def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=[]):
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(loc_query.__name__, query, variables)
    if request.json()['data']['user']['repositories']['pageInfo']['hasNextPage']:
        edges += request.json()['data']['user']['repositories']['edges']
        return loc_query(owner_affiliation, comment_size, force_cache, request.json()['data']['user']['repositories']['pageInfo']['endCursor'], edges)
    else:
        return cache_builder(edges + request.json()['data']['user']['repositories']['edges'], comment_size, force_cache)

def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    cached = True
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError:
        os.makedirs('cache', exist_ok=True)
        data = []
        if comment_size > 0:
            for _ in range(comment_size): data.append('This line is a comment block.\n')
        with open(filename, 'w') as f:
            f.writelines(data)

    if len(data)-comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest():
            try:
                if int(commit_count) != edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']:
                    owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = repo_hash + ' ' + str(edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']) + ' ' + str(loc[2]) + ' ' + str(loc[0]) + ' ' + str(loc[1]) + '\n'
            except TypeError:
                data[index] = repo_hash + ' 0 0 0 0\n'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]

def flush_cache(edges, filename, comment_size):
    with open(filename, 'r') as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size]
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')

def add_archive():
    try:
        with open('cache/repository_archive.txt', 'r') as f:
            data = f.readlines()
        old_data = data
        data = data[7:len(data)-3]
        added_loc, deleted_loc, added_commits = 0, 0, 0
        contributed_repos = len(data)
        for line in data:
            repo_hash, total_commits, my_commits, *loc = line.split()
            added_loc += int(loc[0])
            deleted_loc += int(loc[1])
            if (my_commits.isdigit()): added_commits += int(my_commits)
        added_commits += int(old_data[-1].split()[4][:-1])
        return [added_loc, deleted_loc, added_loc - deleted_loc, added_commits, contributed_repos]
    except FileNotFoundError:
        return [0, 0, 0, 0, 0]

def force_close_file(data, cache_comment):
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)

def stars_counter(data):
    total_stars = 0
    for node in data: total_stars += node['node']['stargazers']['totalCount']
    return total_stars

def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    try:
        tree = etree.parse(filename)
        root = tree.getroot()
        justify_format(root, 'age_data', age_data, 49)

        star_line = f"Repos:....{repo_data} {{Contributed: {contrib_data}}} | Stars:"
        justify_format(root, 'star_data', star_data, 55 - len(star_line))
        justify_format(root, 'repo_data', repo_data, 4 + len(str(repo_data)))
        justify_format(root, 'contrib_data', contrib_data)

        follower_line = f"Commmits:..........{commit_data} | Followers:"
        justify_format(root, 'follower_data', follower_data, 55 - len(follower_line))
        justify_format(root, 'commit_data', commit_data, 10 + len(str(commit_data)))

        loc_val, loc_add_val, loc_del_val = str(loc_data[2]), str(loc_data[0]), str(loc_data[1])
        loc_del_line = f"Lines of Code on GitHub:. {loc_val} ( {loc_add_val}++, -- )"
        justify_format(root, 'loc_del', loc_del_val, 55 - len(loc_del_line))
        justify_format(root, 'loc_add', loc_add_val)
        justify_format(root, 'loc_data', loc_val, 2 + len(loc_val))
        
        for img in root.findall('.//{http://www.w3.org/2000/svg}image'):
            url = img.get('href')
            if url and url.startswith('http'):
                try:
                    img_data = requests.get(url).content
                    image = Image.open(io.BytesIO(img_data))
                    
                    # Crop square avatar targeting vertical portrait preserving a wider area!
                    img_w, img_h = image.size
                    crop_w = int(img_h * 0.76)
                    if crop_w > img_w: crop_w = img_w
                    left, top = int((img_w - crop_w) / 2), 0
                    right, bottom = left + crop_w, img_h
                    image = image.crop((left, top, right, bottom))
                    
                    # Layout 38x30 characters. Max width that allows symmetrical ~18px margins before x=390.
                    width = 38
                    height = 30
                    image = image.resize((width, height)).convert("RGBA")
                    pixels = list(image.getdata())
                    
                    # BFS flood-fill background removal seeded from ALL edge pixels.
                    # Handles JPEG compression noise where corner colors vary slightly.
                    from collections import deque
                    def color_close(c1, c2, tol=25):
                        return all(abs(int(c1[i]) - int(c2[i])) <= tol for i in range(3))
                    
                    # Sample the background color from the entire image border (more reliable than 4 corners)
                    edge_pixels = []
                    for x in range(width):  # top & bottom rows
                        edge_pixels.append(pixels[x])
                        edge_pixels.append(pixels[(height-1)*width + x])
                    for y in range(height):  # left & right columns
                        edge_pixels.append(pixels[y*width])
                        edge_pixels.append(pixels[y*width + width-1])
                    # Compute median background color from all edge pixels
                    bg_r = sorted(p[0] for p in edge_pixels)[len(edge_pixels)//2]
                    bg_g = sorted(p[1] for p in edge_pixels)[len(edge_pixels)//2]
                    bg_b = sorted(p[2] for p in edge_pixels)[len(edge_pixels)//2]
                    bg_color = (bg_r, bg_g, bg_b, 255)
                    
                    # Seed BFS from every edge pixel that matches the background
                    bg_mask = [False] * (width * height)
                    queue = deque()
                    for seed_idx, p in enumerate(pixels):
                        x, y = seed_idx % width, seed_idx // width
                        if (x == 0 or x == width-1 or y == 0 or y == height-1):
                            if color_close(p, bg_color):
                                bg_mask[seed_idx] = True
                                queue.append(seed_idx)
                    while queue:
                        idx = queue.popleft()
                        x, y = idx % width, idx // width
                        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                            nx, ny = x+dx, y+dy
                            if 0 <= nx < width and 0 <= ny < height:
                                nidx = ny * width + nx
                                if not bg_mask[nidx] and color_close(pixels[nidx], bg_color):
                                    bg_mask[nidx] = True
                                    queue.append(nidx)
                    
                    # Map foreground pixels to dense ASCII with high contrast
                    ASCII_CHARS = "@#S%?*+;:,. "
                    if 'dark' in filename:
                        ASCII_CHARS = ASCII_CHARS[::-1]
                    
                    ascii_str = ""
                    for idx, (r, g, b, a) in enumerate(pixels):
                        if a < 50 or bg_mask[idx]:
                            ascii_str += " "  # Background: blank
                        else:
                            gray = int(0.2989*r + 0.5870*g + 0.1140*b)
                            char_idx = min(len(ASCII_CHARS)-1, gray * len(ASCII_CHARS) // 256)
                            ascii_str += ASCII_CHARS[char_idx]
                    
                    # x=195 and text-anchor: middle guarantees perfect symmetrical margin spacing
                    # within the 390px left column, regardless of OS font rendering differences.
                    ascii_text = etree.Element("{http://www.w3.org/2000/svg}text", x="195", y="25", style="text-anchor: middle;")
                    if 'dark' in filename:
                        ascii_text.set('fill', '#c9d1d9')
                    else:
                        ascii_text.set('fill', '#334155')
                        
                    for i in range(height):
                        tspan = etree.SubElement(ascii_text, "{http://www.w3.org/2000/svg}tspan", x="195", dy="16", style="font-family: monospace; font-size: 16px;")
                        # Replace regular spaces with non-breaking spaces ( ) to guarantee text-anchor: middle never trims trailing spaces
                        tspan.text = ascii_str[i * width:(i + 1) * width].replace(" ", " ")
                    
                    parent = img.getparent()
                    parent.insert(parent.index(img), ascii_text)
                    parent.remove(img)
                except Exception as e:
                    print(f"ASCII Image conversion failed: {e}")
        
        tree.write(filename, encoding='utf-8', xml_declaration=True)
    except OSError:
        print(f"Skipping {filename} rewrite as the file was not found.")

def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    find_and_replace(root, f"{element_id}_dots", dot_string)

def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text

def commit_counter(comment_size):
    total_commits = 0
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    with open(filename, 'r') as f:
        data = f.readlines()
    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits

def user_getter(username):
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']

def follower_getter(username):
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])

def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1

def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


if __name__ == '__main__':
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    
    # Initialize from the config provided during generation
    age_data, age_time = perf_counter(daily_readme, datetime.datetime(2004, 10, 16))
    
    total_loc, loc_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], 7)
    commit_data, commit_time = perf_counter(commit_counter, 7)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    if OWNER_ID == {'id': 'MDQ6VXNlcjU3MzMxMTM0'}: 
        archived_data = add_archive()
        for index in range(len(total_loc)-1):
            total_loc[index] += archived_data[index]
        contrib_data += archived_data[-1]
        commit_data += int(archived_data[-2])

    for index in range(len(total_loc)-1): total_loc[index] = '{:,}'.format(total_loc[index]) 

    svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])
    svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])
