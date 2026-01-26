import os
import re

def detect_unused():
    template_dir = 'core/templates'
    search_dirs = ['core/views', 'core/templates']
    
    # 1. Tüm template dosyalarını listele
    all_templates = []
    for root, dirs, files in os.walk(template_dir):
        if '_unused' in root: continue # Zaten işaretlenmişleri geç
        for file in files:
            if file.endswith('.html'):
                # Klasör yapısıyla birlikte ismini al (örn: 'icmal.html')
                rel_path = os.path.relpath(os.path.join(root, file), template_dir).replace('\\', '/')
                all_templates.append(rel_path)

    print(f"--- Toplam {len(all_templates)} şablon inceleniyor ---\n")
    
    unused = []
    for template in all_templates:
        found = False
        # 2. Dosya ismini views ve diğer template'lerde ara
        for s_dir in search_dirs:
            for root, dirs, files in os.walk(s_dir):
                for file in files:
                    if file.endswith(('.py', '.html')):
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            content = f.read()
                            if template in content:
                                found = True
                                break
                if found: break
            if found: break
        
        if not found:
            unused.append(template)

    if unused:
        print("⚠️ Kullanılmıyor gibi görünen dosyalar:")
        for u in unused:
            print(f" - {u}")
    else:
        print("✅ Tüm şablonlar kullanımda görünüyor.")

if __name__ == "__main__":
    detect_unused()