# Dosya: core/decorators.py

from django.shortcuts import redirect
from django.contrib import messages

def yetki_kontrol(user, allowed_roles):
    """
    Kullanıcının belirli rollere (Gruplara) sahip olup olmadığını kontrol eder.
    Kullanım: if not yetki_kontrol(request.user, ['MUHASEBE', 'YONETICI']): return ...
    """
    # 1. Süper kullanıcı (Admin) ise her zaman geçiş izni ver
    if user.is_superuser:
        return True

    # 2. Kullanıcının gruplarını kontrol et (Django Groups)
    # Eğer kullanıcının grubu, izin verilen roller listesindeyse True döner.
    if user.groups.filter(name__in=allowed_roles).exists():
        return True

    # 3. (Opsiyonel) Eğer kullanıcı modelinizde özel bir 'role' alanı varsa:
    # if hasattr(user, 'role') and user.role in allowed_roles:
    #     return True

    return False