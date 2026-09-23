import os
import subprocess
import json

def process_file(source_file, png_file):
    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    start = content.find('```mermaid\n')
    if start != -1:
        start += len('```mermaid\n')
        end = content.find('```', start)
        mermaid_code = content[start:end].strip()
    else:
        mermaid_code = content.strip()
    
    temp_mmd = source_file.rsplit('.', 1)[0] + '_temp.mmd'
    with open(temp_mmd, 'w', encoding='utf-8') as f:
        f.write(mermaid_code)
        
    print(f'Generating {png_file} from {source_file}...')
    try:
        subprocess.run(['npx', '-y', '@mermaid-js/mermaid-cli', '-i', temp_mmd, '-o', png_file, '--puppeteerConfigFile', 'puppeteer-config.json'], check=True, shell=True)
        print(f'Successfully generated {png_file}')
    except Exception as e:
        print(f'Error generating {png_file}: {e}')
    finally:
        if os.path.exists(temp_mmd):
            os.remove(temp_mmd)

with open('puppeteer-config.json', 'w') as f:
    json.dump({
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        "executablePath": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
    }, f, indent=2)

if os.path.exists('arch.md'):
    process_file('arch.md', 'architecture.png')
elif os.path.exists('arch.txt'):
    process_file('arch.txt', 'architecture.png')

if os.path.exists('math_workflow.md'):
    process_file('math_workflow.md', 'math_workflow.png')
elif os.path.exists('math_workflow.txt'):
    process_file('math_workflow.txt', 'math_workflow.png')
