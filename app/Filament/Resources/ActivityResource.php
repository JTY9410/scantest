<?php

namespace App\Filament\Resources;

use App\Filament\Resources\ActivityResource\Pages;
use App\Models\Activity;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;

class ActivityResource extends Resource
{
    protected static ?string $model = Activity::class;

    protected static ?string $navigationIcon = 'heroicon-o-clipboard-document-list';

    protected static ?string $navigationGroup = '시스템';

    protected static ?string $modelLabel = '활동 기록';

    protected static ?string $pluralModelLabel = '활동 기록';

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Select::make('user_id')
                    ->relationship('user', 'name')
                    ->label('사용자')
                    ->required(),
                Forms\Components\TextInput::make('ip')
                    ->label('IP 주소')
                    ->required(),
                Forms\Components\TextInput::make('relation')
                    ->label('관련 모델')
                    ->required(),
                Forms\Components\TextInput::make('relation_type')
                    ->label('활동 유형')
                    ->required(),
                Forms\Components\TextInput::make('relation_id')
                    ->label('관련 ID')
                    ->required(),
                Forms\Components\KeyValue::make('changes')
                    ->label('변경사항')
                    ->columnSpanFull(),
                Forms\Components\Textarea::make('message')
                    ->label('메시지')
                    ->columnSpanFull(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('user.name')
                    ->label('사용자')
                    ->searchable()
                    ->sortable(),
                Tables\Columns\TextColumn::make('ip')
                    ->label('IP 주소')
                    ->searchable(),
                Tables\Columns\TextColumn::make('relation')
                    ->label('관련 모델')
                    ->searchable(),
                Tables\Columns\TextColumn::make('relation_type')
                    ->label('활동 유형')
                    ->searchable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('생성일')
                    ->dateTime('Y-m-d H:i:s')
                    ->sortable(),
            ])
            ->defaultSort('created_at', 'desc')
            ->filters([
                //
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
            ])
            ->bulkActions([
                //
            ]);
    }

    public static function getRelations(): array
    {
        return [
            //
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListActivities::route('/'),
            'view' => Pages\ViewActivity::route('/{record}'),
        ];
    }
}
