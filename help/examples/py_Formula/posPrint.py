import win32print

# Замініть "Generic / Text Only" на точну назву вашого принтера
printer_name = "Generic / Text Only"

def send_to_printer(text):
    # Відкриваємо принтер
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        # Створюємо завдання на друк у режимі RAW (сирі дані)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("POS_Print", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        
        # Кодуємо текст у CP866 (стандарт для чекових принтерів з кирилицею)
        raw_data = text.encode('cp866', errors='ignore')
        
        win32print.WritePrinter(hPrinter, raw_data)
        
        # Команда ESC/POS для повної обрізки паперу (якщо принтер підтримує)
        # cut_command = b'\x1d\x56\x00'
        # win32print.WritePrinter(hPrinter, cut_command)
        
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    finally:
        win32print.ClosePrinter(hPrinter)

send_to_printer("Вітаю! Друк працює успішно.\n\n\n")