def yetki_kontrol(user, izinli_gruplar):
    if user.is_superuser:
        return True
    if not user.groups.exists():
        return False
    user_groups = user.groups.values_list('name', flat=True)
    for grup in user_groups:
        if grup in izinli_gruplar:
            return True
    return False