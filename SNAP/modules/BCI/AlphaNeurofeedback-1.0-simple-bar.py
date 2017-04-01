# -*- coding: UTF-8 -*-

'''
Procedura: AlphaNeurofeedback
Autor: Krzysztof Kutt, 2016

Cel procedury: Trening asymetrii przedczołowej alfy u sportowców
               (zwiększenie aktywności lewej półkuli -> więcej
               pozytywnych emocji -> lepsze wyniki) 

Budowa procedury (obsługuje całą jedną sesję z badanym):
  1. kalibracja (ustalenie aktualnego poziomu alfy jako punktu wyjścia):
     badany tylko patrzy na punkt fiksacji
  2. blok kilkuminutowy, w czasie którego badany skupia się na punkcie
     fiksacji i jego zadaniem jest przesunięcie wyświetlanego słupka
     w górę
  3. po każdym bloku następuje chwila przerwy (do naciśnięcia spacji)

Sterowanie:
  * Esc - wyłączenie procedury;
  * F2 - przerwanie procedury (pozostaje szary ekran);
  * F1 - rozpoczęcie procedury (na samym początku albo
         gdy przerwana klawiszem F2);
  * Spacja - uruchomienie + wznowienie po przerwie
  * Enter - gdy chcemy wyjść z aktualnego bloku i przeskoczyć do przerwy;
            w czasie kalibracji: przerywa i wykorzystuje poprzednie wartości
            asymKalibracja i asymSkalar (przydatne np. po restarcie procedury)
  * Backspace - gdy chcemy wrócić do przerwy przed aktualnym blokiem

Trzy warunki:
  - A (asymetria): true feedback - maksymalizowanie RÓŻNICY mocy alfa R-L 
  - R (relaks): true feedback - maksymalizowanie SUMY mocy alfa L+R
  - F (fałszywy): false feedback - odtwarzanie zapisu aktywności innej osoby
    z innej sesji prawdziwego feedbacku

Grupy (A = 9xA; F = 3xF, R = 6xR) -- mogą być edytowane poniżej
  - AFR
  - ARF
  - FAR
  - FRA
  - RAF
  - RFA

Powiązane moduły i narzędzia:
  - AlphaProcessing w Pythonie -> zbiera EEG, analizuje w czasie
    rzeczywistym i przekazuje moc lewej i prawej półkuli za pośrednictwem
    Lab Stream Layer; obliczanie sumy / różnicy jest robione dopiero
    w tej procedurze!
  - Lab Stream Layer --> narzędzie/protokół do przesyłania przez sieć
    aktualnego poziomu asymetrii (od BCILAB do tej procedury)

Zbierane dane:
  - W tej procedurze (w pliku badani\ImieNazwisko.osb):
    * parametry procedury (ilość i długość bloków)
    * przypisanie badanego do warunku badawczego
    * wartości wyliczone w trakcie kalibracji
    * statystyki sesji (min, max, std, mean asymetria)
    * skuteczność badanego (szybkość osiągnięcia progu, czas powyżej progu)
    * FIXME: w warunku fake: informacja o tym która sesja była odczytywana
  - W tej procedurze (w plikach rejestry\ImieNazwisko.XX.YY.alfa):
    * poziomy alfy dla lewej i prawej półkuli (w tej kolejności,
      oddzielone spacją) dla sesji XX i bloku YY

  - W ActiView:
    * plik ImięNazwisko.sesjaXX.bdf: EEG + triggery

Triggery: (można je zmienić niżej)
  * 1 - Początek kalibracji
  * 2 - Początek bloku/koniec przerwy
  * 3 - Koniec bloku/początek przerwy
  * 4 - Zmiana wyświetlanego poziomu (konkretna wartość do odczytania

Konfiguracja:
  * wartości domyślne znajdują się poniżej w __init__
  * mogą zostać nadpisane w pliku study.cfg
  * wszystko może zostać nadpisane w pliku badanego ImieNazwisko.osb
    
  * równolegle można konfigurować sposób wyświetlania:
    pliki fullscreen.prc, windowed.prc w folderze study

'''

from framework.latentmodule import LatentModule
import os, traceback, time, numpy, random

from pylsl.pylsl import StreamInlet, resolve_byprop

## do komunikatów dla badacza na początku:
from Tkinter import Tk, Label, Entry, Button, W
import tkMessageBox
from tkFileDialog import askopenfilename

import labjackU3


class Main(LatentModule):
    
    def __init__(self):
        LatentModule.__init__(self)
        
        # przeładowanie kodowania na utf, żeby działały komunikaty
        # (Eclipse domyślnie ma utf, więc nie bylo tego widać wcześniej)
        import sys
        reload(sys).setdefaultencoding("utf-8")
        
        '''
        KONFIGURACJA BADANIA 
        (może zostać nadpisana w pliku .cfg danego study)
        
        folderBadani - folder z plikami konfiguracyjnymi osób badanych
        folderRejestry - folder z zapisami przebiegów sesji
        dlugKalibracji - czas trwania bloku kalibracji (w minutach)
        dlugBloku - czas trwania pojedynczego bloku (w minutach)
        iloscBlokow - ilość bloków składających się na całą sesję 
        poziomWysokosc - maksymalna wysokość wyświetlanego paska
        poziomSzerokosc - szerokość wyświetlanego paska
        poziomKolorOK, poziomKolorZLY - kolor paska, gdy jest powyżej/poniżej 0  
        '''
        self.folderBadani = 'studies\\Neurofeedback\\badani'
        self.folderRejestry = 'studies\\Neurofeedback\\rejestry'
        self.dlugKalibracji = 1.0
        self.dlugBloku = 6.0
        self.iloscBlokow = 5
        self.poziomWysokosc = 0.5
        self.poziomSzerokosc = 0.05
        self.poziomKolorOK = [40.0/255.0, 215.0/255.0, 40.0/255.0, 1]
        self.poziomKolorZLY = [215.0/255.0, 40.0/255.0, 40.0/255.0, 1]
        
        self.triggerKalibracja = 1
        self.triggerBlok = 2
        self.triggerPrzerwa = 3
        self.triggerZmianaPoziomu = 4
        
        self.grupy = ["AAAAAAAAAFFFRRRRRR",  # AFR
                      "AAAAAAAAARRRRRRFFF",  # ARF
                      "FFFAAAAAAAAARRRRRR",  # FAR
                      "FFFRRRRRRAAAAAAAAA",  # FRA
                      "RRRRRRAAAAAAAAAFFF",  # RAF
                      "RRRRRRFFFAAAAAAAAA"]  # RFA
        
        '''
        WARTOŚCI DLA DANEJ OSOBY BADANEJ
        (mogą zostać nadpisane w pliku .osb danej osoby badanej)
        
        grupy - (opisane wyżej)
        nrSesji - aktualny numer sesji (1 dla nowej osoby badanej)
        imieNazwisko - imię i nazwisko osoby badanej
        '''
        self.grupa = random.choice(self.grupy)
        self.nrSesji = 1
        self.imieNazwisko = ""
        
        
        '''
        INNE WARTOŚCI GLOBALNE WYKORZYSTYWANE W PROCEDURZE
        
        plikBadanego - ścieżka bezwzględna do pliku .osb badanego
        warunek - A = Adaptacja; R = Relaks; F = Fałszywy
                  (szczegółowy opis znajduje się na początku skryptu)
                  wartość domyślna = losowanie dla nowych badanych;
                  dla kolejnych sesji po prostu wczytujemy wartość
                  z pliku konfiguracyjnego danej osoby badanej
        poziomyLEWY - zbiór wszystkich poziomów LEWEJ alfy
        poziomyPRAWY - zbiór wszystkich poziomów PRAWEJ alfy
        poziomyFINAL - zbiór wszystkich wartości wyliczonych poziomów
                       (i wyświetlanych użytkownikowi w true feedback)
        poczatekBloku - indeks pierwszego elementu z aktualnego bloku
                        (w powyższych tabelach)
        asymSkalar - wspolczynnik skalowania wartosci z BCI do wysokości
                     wyswietlanego paska (wyliczany na podstawie wartości
                     z kalibracji i zadanego progu)
        asymKalibracja - wartość asymetri wyliczona podczas kalibracji
        czasNaRysowanie - opóźnienie po rysowaniu punktu fiksacji
                          i prostokąta, aby zdążyły się pojawić na ekranie
        wcisnietyKlawisz - obsługa klawiszy do sterowania procedurą
        strumien - strumień LabStreamLayer do odbierania poziomów alfy
        '''
        self.plikBadanego = ""
        self.warunek = "A"  #warunek jest wyliczany po stworzeniu/wczytaniu pliku
        self.poziomyLEWY = []
        self.poziomyPRAWY = []
        self.poziomyFINAL = []
        self.poczatekBloku = 0
        self.asymSkalar = 0.5
        self.asymKalibracja = 0.0
        self.czasNaRysowanie = 0.1
        self.wcisnietyKlawisz = ""
        self.strumien = None
        
        ''' przypisanie zdarzeń dla obsługiwanych klawiszy '''
        self.accept("enter", self.obsluzKlawisz, ["enter"])
        self.accept("backspace", self.obsluzKlawisz, ["backspace"])


        ## inicjalizacja karty do triggerów!
        labjackU3.configure()


    def run(self):
        ''' ----------------------------------------------------------------- 
            -------------------- OBSŁUGA PLIKÓW BADANYCH --------------------
            ----------------------------------------------------------------- '''
        Tk().withdraw() # nie chcemy GUI Tinkera, to nie pozwala głównemu oknu się pojawić
        
        result = tkMessageBox.askquestion("Konfiguracja", "Czy to jest pierwsza sesja osoby badanej?",
                                          icon='question')
        if result == 'yes':
            """ pierwsza sesja - podajemy nazwę pliku + losujemy grupę """
            top = Tk()
            
            Label(top, text="Wprowadz nazwe pliku uzytkownika w formacie ImieNazwisko\n" + 
                  "(bez spacji i polskich znakow, imie i nazwisko zacznij od duzej litery).\n" + 
                  "Np. LukaszNowak",  font=("Times New Roman", 13)).grid(row=0,columnspan=2)
            E1 = Entry(top, bd = 3, width=40)
            E1.grid(row=1)
            Button(top, text="OK", width=15, command=lambda: self.check_filename(top, E1)).grid(row=1,
                                                                    column=1, sticky=W, pady=4)
            top.wm_title("Tworzenie pliku nowej osoby badanej")
            
            # wyśrodkuj okienko
            top.update_idletasks()
            w = top.winfo_screenwidth()
            h = top.winfo_screenheight()
            size = tuple(int(_) for _ in top.geometry().split('+')[0].split('x'))
            x = w/2 - size[0]/2
            y = h/2 - size[1]/2
            top.geometry("%dx%d+%d+%d" % (size + (x, y)))
            
            # brak możliwości zmiany rozmiaru
            top.resizable(0,0)
            
            # pętla nieskończona (działa dopóki badany nie poda właściwej nazwy pliku)
            top.mainloop()
            
            # tutaj już mamy ustaloną nazwę pliku (z funkcji sprawdzającej w GUI)
            # tworzymy ten plik...
            open(self.plikBadanego, 'a').close()
            # ... i zapisujemy początkowe ustawienia osoby badanej
            self.write_to_subject_file('imieNazwisko = "' + str(self.imieNazwisko) + '"\n' +
                                       'grupa = "' + str(self.grupa) + '"\n',
                                       "Ustawienia poczatkowe")

        else:
            """ kolejna sesja - wybieramy plik danej osoby i wczytujemy dane """
            while self.plikBadanego == "":
                self.plikBadanego = askopenfilename(initialdir = self.folderBadani,
                                                    filetypes = [('Pliki osób badanych', '.osb')])
                if self.plikBadanego == "":
                    tkMessageBox.showerror("Uwaga", "Wybierz plik osoby badanej!")
            
            # wczytujemy dane (na podstawie kodu z launcher.py)
            try:
                if not os.path.exists(self.plikBadanego):
                    print 'Plik badanego "' + self.plikBadanego + '" nie znaleziony.'
                else:
                    with open(self.plikBadanego,'r') as f:
                        print 'Wczytywanie parametrow z pliku badanego...',
                        for line in f.readlines():
                            exec line in self.__dict__
                        print 'Zrobione.'
            except Exception,e:
                print 'Problem z wczytywaniem informacji z pliku "' + self.plikBadanego + '".'
                print e
                traceback.print_exc()
        
        # ustalanie warunku na aktualną sesję
        # jeżeli zdarzy się nadmiarowa sesja to będzie to domyślna wartość czyli "A"
        if len(self.grupa) >= self.nrSesji:
            self.warunek = self.grupa[self.nrSesji-1]
        
        # zapisywanie informacji o początku sesji do pliku
        self.write_to_subject_file('\n\n##### Początek sesji ' + str(self.nrSesji) + ' -- ' +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' +
                           '### Parametry sesji:\n' + 
                           '# warunek = ' + str(self.warunek) +
                           '\n# dlugKalibracji = ' + str(self.dlugKalibracji) +
                           '\n# iloscBlokow = ' + str(self.iloscBlokow) + 
                           '\n# dlugBloku = ' + str(self.dlugBloku) + '\n',
                           'Informacje o nowej sesji')
        
        #FIXME: wczytywanie plików z zapisem sesji
        #FIXME: zapisywanie parametrów Fake Feedback do pliku
        
        
        ''' ----------------------------------------------------------
            -------------------- POCZATEK BADANIA --------------------
            ---------------------------------------------------------- '''
        # uzyskanie dostępu do poziomów alfy przesyłanych przez sieć
        streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                 timeout = 3)
        while len(streams) == 0:
            self.write("UWAGA! Procedura na laptopie nie zostala wlaczona!")
            streams = resolve_byprop(prop = 'name', value = 'BCIAlphaLevel',
                                     timeout = 3)
        self.strumien = StreamInlet(streams[0])
        
        print "PROCEDURA ZAINICJALIZOWANA! NACISNIJ SPACJE, ABY ROZPOCZAC"
        self.write('Witaj! To jest Twoja ' + str(self.nrSesji) + '. sesja.' +
                   u'\nZaczniemy ją już niedługo!','space')
        
        ''' ----------------------------------------------------
            -------------------- KALIBRACJA --------------------
            ---------------------------------------------------- 
            zbieramy aktualny poziom różnicy alfy i wyliczamy średni poziom
            jako punkt 50% wysokości paska (aby była możliwość ruszać się
            w górę i w dół w trakcie procedury) '''        
        print("Poczatek kalibracji...  "),
       
        for k in range(5,0,-1):
            self.write('Kalibracja rozpocznie się za '+str(k)+'.'+
                       '\nProszę patrz na + pośrodku ekranu i postaraj' +
                       ' się nie ruszać.')
        labjackU3.trigger(self.triggerKalibracja)
        
        punktFiks = self.crosshair(100000,size=0.2,width=0.005,block=False)
        self.sleep(self.czasNaRysowanie)  # czas na pojawienie się punktu fiksacji
        
        self.poziomyFINAL = []
        self.strumien.pull_chunk()  # wyciągnij wszystkie próbki, które były do tej pory
        self.wcisnietyKlawisz = ""  # skasuj klawisze wciśnięte do tej pory
        koniecCzasu = time.time() + 60.0*self.dlugKalibracji
        
        while time.time() < koniecCzasu:
            # pobierz kolejny poziom alfy
            self.poziomyFINAL.append(self.read_and_calculate_alpha(False))
            
            self.sleep(self.czasNaRysowanie)  # czas na obsluge ew. klawisza
            
            # przerywamy zbieranie danych do kalibracji
            if self.wcisnietyKlawisz == "enter":
                break
                
        if self.wcisnietyKlawisz == "enter":
            #nie robimy nic; do kalibracji zostaje wartosc poprzednia,
            #wyliczona podczas poprzedniej sesji i zapisana w pliku (ew. domyślna)
            #(na wypadek np. przerwanej procedury, która została wznowiona)
            self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
            print("Kalibracja przerwana. Uzyte poprzednie wartosci")
        else:    # wyliczamy skalar do przeliczania wartości z BCI na wysokość paska
            self.asymKalibracja = numpy.mean(self.poziomyFINAL)
            print("Asymetria wyliczona: " + str(self.asymKalibracja))
            
#            ## chcemy, żeby poziom z kalibracji oznaczał 50% wysokości paska
#            if self.asymKalibracja == 0:
#                # nie mamy jak wyliczyć skalara, więc zostaje domyślny
#                pass
#            else:
#                skalarTemp = (0.5 * self.poziomWysokosc) / self.asymKalibracja
#                if skalarTemp < 0:   #skalar musi byc dodatni
#                    skalarTemp = -skalarTemp
#                self.asymSkalar = skalarTemp
            # FIXME: roboczo współczynniki skalowania są podane na sztywno
            # FIXME: zrobić jakieś wyliczanie nie na podstawie średniej, ale
            #        na podstawie minimalnej i maksymalnej wartości
            #        osiągniętej w czasie kalibracji?
            if( self.warunek == 'R' ):
                self.asymSkalar = 0.025
            else:
                self.asymSkalar = 0.25
            
            #zapisujemy wyliczone wartości do pliku
            self.write_to_subject_file("asymKalibracja = " + str(self.asymKalibracja) +
                               "\nasymSkalar = " + str(self.asymSkalar) + '\n',
                               "Dane kalibracji")
        
        
        ''' ------------------------------------------------------------
            -------------------- BLOK NEUROFEEDBACK --------------------
            ------------------------------------------------------------ '''
        
        self.poziomyFINAL = []   #usuwamy dane z kalibracji
        prost = None
        
        punktFiks.destroy()  #usuwamy punkt fiksacji podczas instrukcji
        blok = 1
        while blok <= self.iloscBlokow:
            ## przerwa (wyświetlenie komunikatu i oczekiwanie na spację)
            labjackU3.trigger(self.triggerPrzerwa)
            
            self.write('Czas na chwilę przerwy! Przed Tobą jeszcze ' +
                       str(self.iloscBlokow+1-blok) + ' z ' + 
                       str(self.iloscBlokow) + ' bloków.','space')
            
            for k in range(5,0,-1):
                self.write('Blok ' + str(blok) + ' z ' + str(self.iloscBlokow) + 
                           ' rozpocznie się za '+ str(k)+'.'+
                           '\n\nTwoim zadaniem jest sprawienie, aby słupek' +
                           ' na ekranie sięgał jak najwyżej.'
                           '\nProszę patrz na + pośrodku ekranu i postaraj' +
                           ' się nie ruszać.')
            
            punktFiks = self.crosshair(100000,size=0.2,width=0.005,block=False)
            
            self.strumien.pull_chunk()  # wyciągnij wszystkie próbki, które były w czasie przerwy
            self.wcisnietyKlawisz = ""  # skasuj klawisze z przerwy
            koniecCzasu = time.time() + 60.0*self.dlugBloku
            
            # początek bloku!
            labjackU3.trigger(self.triggerBlok)
            
            while time.time() < koniecCzasu:
                # pobierz kolejny poziom alfy
                alfa = self.read_and_calculate_alpha()
                self.poziomyFINAL.append(alfa)
                
                ''' WYLICZ ROZMIAR PROSTOKATA '''
                if self.warunek == "F":   ## FAKE FEEDBACK
                    # FIXME: DO PRZYGOTOWANIA!
                    # FAKE FEEDBACK będzie polegał na odtwarzaniu bloku z pliku
                    # jeśli braknie nam próbek (bo np. sesja nagrana trwała o 1-2 próbki
                    # krócej) to cofamy się od końca tabeli w kierunku początku, żeby
                    # cały czas była jakaś zmienność poziomu
                    poziom = 0
                    pass
                
                else:  ## PRAWDZIWY FEEDBACK
                    poziom = alfa * self.asymSkalar
                
                #zaktualizuj prostokat:
                if poziom < 0:
                    kolor = self.poziomKolorZLY
                else:
                    kolor = self.poziomKolorOK
                if prost is not None:
                    prost.destroy()  #skasuj poprzedni prostokąt
                prost = self.rectangle([-self.poziomSzerokosc,self.poziomSzerokosc,
                                       max(0,poziom),min(0,poziom)],0,block=False,
                                       color=kolor)
                # trigger zmiana wyswietlanego wypoziomu
                labjackU3.trigger(self.triggerZmianaPoziomu)
                self.sleep(self.czasNaRysowanie) #czas na przerysowanie ekranu
                
                # przerywamy blok i idziemy do kolejnego
                if self.wcisnietyKlawisz == "enter":
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
                # przerywamy blok i zaczynamy go od początku
                elif self.wcisnietyKlawisz == "backspace":
                    blok -= 1
                    self.wcisnietyKlawisz = ""  # obsłużyliśmy, więc czyścimy
                    break
            
            if self.warunek != "F":
                self.write_to_session_file(blok)  # zapisz przebieg bloku do pliku
            
            prost.destroy()  # usuwamy na czas przerwy
            punktFiks.destroy()  # usuwamy na czas przerwy
        
            blok += 1   # przechodzimy do kolejnego bloku
            
        
        ''' --------------------------------------------------------------
            -------------------- KONIEC: ZAPIS DANYCH --------------------
            -------------------------------------------------------------- '''
        
        # trigger przerwy na koniec
        labjackU3.trigger(self.triggerPrzerwa)
        napisKoniec = self.write('To już koniec na dzisiaj. Dziękujemy za' +
                                 ' udział w treningu!\n\n ', duration = 0,
                                 block = False)
        
        sredniPoziom = numpy.mean(self.poziomyFINAL)
        minPoziom = numpy.min(self.poziomyFINAL)
        maxPoziom = numpy.max(self.poziomyFINAL)
        odchStdPoziom = numpy.std(self.poziomyFINAL)
        
        self.write_to_subject_file("### Statystyki sesji:\n" + 
                           "# sredniPoziom = " + str(sredniPoziom) +
                           "\n# minPoziom = " + str(minPoziom) + 
                           "\n# maxPoziom = " + str(maxPoziom) + 
                           "\n# odchStdPoziom = " + str(odchStdPoziom) + "\n",
                           "Statystyki sesji")
        
        czasPowyzejProgu0 = len([i for i in self.poziomyFINAL if i >= 0.0])
        procPowyzejProgu0 = (100.0 * czasPowyzejProgu0) / len(self.poziomyFINAL)
        if czasPowyzejProgu0 == 0:
            czasDoProgu0 = -1
            procDoProgu0 = -100.0
        else:
            czasDoProgu0 = next(i for i,v in enumerate(self.poziomyFINAL) if v > 0.0)
            procDoProgu0 = (100.0 * czasDoProgu0) / len(self.poziomyFINAL) 
        
        self.write_to_subject_file("### Skuteczność:\n" + 
                           "## Pierwsze przekroczenie progu 0 (w sek i w %)\n" +
                           "# czasDoProgu0 = " + str(czasDoProgu0) + "\n" +
                           "# procDoProgu0 = " + str(procDoProgu0) + "%\n" +
                           "## Czas powyżej progu 0 (w sek i w %)\n" +
                           "# czasPowyzejProgu0 = " + str(czasPowyzejProgu0) + "\n" +
                           "# procPowyzejProgu0 = " + str(procPowyzejProgu0) + "%\n",
                           "Skutecznosc")
        
        self.write_to_subject_file("##### Koniec sesji " + str(self.nrSesji) + " -- " +
                           time.strftime("%d.%m.%Y %H:%M:%S") + ' ##### \n' + 
                           "\nnrSesji = " + str(self.nrSesji + 1) + '\n',
                           "Koniec zapisu sesji")
        
        napisKoniec.destroy()
        self.write('To już koniec na dzisiaj. Dziękujemy za' +
                   ' udział w treningu!\n\n Dane sesji zostały zapisane.',
                   duration = 0,
                   block = False)



    """ ----------------------------------------------
        ------------  FUNKCJE POMOCNICZE  ------------
        ---------------------------------------------- """

    def read_and_calculate_alpha(self, save = True):
        """"Wczytaj kolejną próbkę z LabStreamLayer i oblicz aktualny poziom
            (na podstawie warunku)
            save -- czy zapisywać poziomy LEWY / PRAWY do tablic czy nie
            (podczas kalibracji nie zapisujemy, tylko w czasie bloków)
        """
        sample,_timestamp = self.strumien.pull_sample()
        lewa = sample[0]
        prawa = sample[1]
        
        # obliczanie poziomu alfy za Davidsonem 1995
        poziom = 0
        if self.warunek == "A":
            poziom = numpy.log10(prawa) - numpy.log10(lewa)
        elif self.warunek == "R":
            poziom = numpy.log10(prawa) + numpy.log10(lewa)
            
        if save:
            self.poziomyLEWY.append(lewa)
            self.poziomyPRAWY.append(prawa)
        
        return poziom


    def check_filename(self, top, entry):
        """"Sprawdź czy plik o takiej nazwie już istnieje;
            Jeśli tak: komunikat
            Jeśli nie: utwórz plik
        """
        nazwaPliku = self.folderBadani + "\\" + entry.get() + ".osb"
        
        if len(entry.get()) < 5:
            tkMessageBox.showerror("Uwaga", "Nazwa pliku powinna zawierac co najmniej 5 znakow!")
        elif os.path.exists(nazwaPliku):
            tkMessageBox.showerror("Uwaga", "Plik o podanej nazwie juz istnieje!")
        else:
            self.plikBadanego = nazwaPliku
            self.imieNazwisko = entry.get()
            top.withdraw()  #schowaj okienko
            top.quit()      #wyjdź z pętli GUI i wróć do procedury


    def write_to_session_file(self, blok):
        ''' zapisz przebieg bloku (wszystkie poziomy lewej i prawej alfy)
            do pliku rejestry/ImieNazwisko.XX.YY.alfa
            (XX - sesja, YY - alfa)
            pierwsza wartość to asymSkalar
        ''' 
        
        nazwaPliku = self.folderRejestry + "\\" + self.imieNazwisko + "." + str(self.nrSesji) + "." + str(blok) + ".alfa"  
        
        try:
            if os.path.exists(nazwaPliku):
                print 'Plik "' + nazwaPliku + '" juz istnieje. Nadpisywanie pliku!'
            with open(nazwaPliku,'w') as f:
                print "Zapisywanie poziomow z bloku " + str(blok) + " do pliku...",
                f.write(str(self.asymSkalar) + "\n")
                for i in range(self.poczatekBloku, len(self.poziomyLEWY)):
                    f.write(str(self.poziomyLEWY[i]) + " " + str(self.poziomyPRAWY[i]) + "\n")
                self.poczatekBloku = len(self.poziomyLEWY)  # przesuwamy znacznik na poczatek kolejnego bloku
                print 'Zrobione.'
        except Exception,e:
            print 'Problem z zapisywaniem informacji do pliku "' + nazwaPliku + '".'
            print e
            traceback.print_exc()


    def write_to_subject_file(self, text, comment):
        try:
            if not os.path.exists(self.plikBadanego):
                print 'Plik badanego "' + self.plikBadanego + '" nie znaleziony.'
            else:
                with open(self.plikBadanego,'a') as f:
                    print comment + " wpisywane do pliku...",
                    f.write(text)
                    print 'Zrobione.'
        except Exception,e:
            print 'Problem z zapisywaniem informacji do pliku "' + self.plikBadanego + '".'
            print e
            traceback.print_exc()


    def obsluzKlawisz(self, klawisz):
        self.wcisnietyKlawisz = klawisz
