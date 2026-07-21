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
                    
                    # INCREASED HEIGHT - Made taller for vertical portrait
                    width = 36  # Keep width same
                    ratio = image.height / image.width
                    height = int(width * ratio * 2.5)  # Increased multiplier from 0.6 to 2.5
                    image = image.resize((width, height)).convert("L")
                    pixels = image.getdata()
                    
                    # Extended ASCII characters for better detail with height increase
                    ASCII_CHARS = ["█", "▓", "▒", "░", "@", "%", "#", "*", "+", "=", "-", ":", ".", " "]
                    if 'dark' in filename:
                        ASCII_CHARS = ASCII_CHARS[::-1]  # Reverse for dark mode
                        
                    ascii_str = ""
                    for pixel in pixels:
                        char_idx = pixel // (256 // len(ASCII_CHARS))
                        if char_idx >= len(ASCII_CHARS): 
                            char_idx = len(ASCII_CHARS) - 1
                        ascii_str += ASCII_CHARS[char_idx]
                    
                    # Adjusted Y position to accommodate taller image
                    ascii_text = etree.Element("{http://www.w3.org/2000/svg}text", x="35", y="95")
                    if 'dark' in filename:
                        ascii_text.set('fill', '#c9d1d9')
                    else:
                        ascii_text.set('fill', '#334155')
                    
                    # Smaller font to fit more rows
                    font_size = 10
                    line_height = 10
                        
                    for i in range(height):
                        tspan = etree.SubElement(ascii_text, "{http://www.w3.org/2000/svg}tspan", 
                                                x="35", dy=str(line_height), 
                                                style=f"font-family: monospace; font-size: {font_size}px; letter-spacing: 0px;")
                        tspan.text = ascii_str[i * width:(i + 1) * width]
                    
                    parent = img.getparent()
                    parent.insert(parent.index(img), ascii_text)
                    parent.remove(img)
                except Exception as e:
                    print(f"ASCII Image conversion failed: {e}")
        
        tree.write(filename, encoding='utf-8', xml_declaration=True)
    except OSError:
        print(f"Skipping {filename} rewrite as the file was not found.")
