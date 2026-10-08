from simple_auction.services.makers import guess_maker


def test_guess_maker_canonical_and_aliases():
    assert guess_maker("Remington 870 Wingmaster - Good") == "Remington"
    assert guess_maker("1972 S&W Model 29 .44 Magnum") == "Smith & Wesson"
    assert guess_maker("smith and wesson model 10") == "Smith & Wesson"
    assert guess_maker("Sig P226") == "SIG Sauer"
    assert guess_maker("H&R Topper") == "Harrington & Richardson"


def test_guess_maker_whole_words_only():
    assert guess_maker("Coltrane custom") is None
    assert guess_maker("Ruger-made") == "Ruger"


def test_earliest_maker_wins():
    assert guess_maker("Winchester barrel on a Marlin action") == "Winchester"
