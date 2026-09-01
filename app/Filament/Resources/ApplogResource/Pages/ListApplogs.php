<?php

namespace App\Filament\Resources\ApplogResource\Pages;

use App\Filament\Resources\ApplogResource;
use Filament\Actions;
use Filament\Resources\Pages\ListRecords;

class ListApplogs extends ListRecords
{
    protected static string $resource = ApplogResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
