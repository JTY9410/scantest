<?php

namespace App\Filament\Pages;

use App\Support\EnvFile;
use Filament\Actions\Action;
use Filament\Forms;
use Filament\Forms\Concerns\InteractsWithForms;
use Filament\Forms\Contracts\HasForms;
use Filament\Forms\Form;
use Filament\Forms\Set;
use Filament\Notifications\Notification;
use Filament\Pages\Page;
use Illuminate\Support\Str;

class SystemSettings extends Page implements HasForms
{
    use InteractsWithForms;

    protected static ?string $navigationIcon = 'heroicon-o-cog-6-tooth';

    protected static string $view = 'filament.pages.system-settings';

    protected static ?string $navigationLabel = '시스템 설정';

    protected static ?string $title = '시스템 설정';

    protected static ?string $navigationGroup = '관리';

    protected static ?int $navigationSort = 99;

    public ?array $data = [];

    public function mount(): void
    {
        $env = EnvFile::base();
        $this->form->fill([
            'app_key' => $env->get('APP_KEY', (string) config('app.key')),
            'jwt_secret' => $env->get('JWT_SECRET', (string) config('jwt.secret')),
            'db_password' => '',
        ]);
    }

    public function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Section::make('APP_KEY')
                    ->description('Laravel 암호화 키입니다. 저장 후 앱 컨테이너를 재시작하세요.')
                    ->schema([
                        Forms\Components\TextInput::make('app_key')
                            ->label('APP_KEY')
                            ->required()
                            ->maxLength(128)
                            ->suffixAction(
                                Forms\Components\Actions\Action::make('generateAppKey')
                                    ->label('생성')
                                    ->action(function (Set $set) {
                                        $set('app_key', 'base64:'.base64_encode(random_bytes(32)));
                                    })
                            ),
                    ]),
                Forms\Components\Section::make('JWT_SECRET')
                    ->description('JWT 서명에 사용하는 64자 비밀키입니다.')
                    ->schema([
                        Forms\Components\TextInput::make('jwt_secret')
                            ->label('JWT_SECRET')
                            ->required()
                            ->minLength(32)
                            ->maxLength(128)
                            ->suffixAction(
                                Forms\Components\Actions\Action::make('generateJwt')
                                    ->label('생성')
                                    ->action(function (Set $set) {
                                        $set('jwt_secret', Str::random(64));
                                    })
                            ),
                    ]),
                Forms\Components\Section::make('DB_PASSWORD')
                    ->description('비워두면 기존 값을 유지합니다. 변경하면 MariaDB 사용자 비밀번호와 맞춰야 합니다.')
                    ->schema([
                        Forms\Components\TextInput::make('db_password')
                            ->label('DB_PASSWORD')
                            ->password()
                            ->revealable(),
                    ]),
            ])
            ->statePath('data');
    }

    public function save(): void
    {
        $data = $this->form->getState();
        $updates = [
            'APP_KEY' => $data['app_key'],
            'JWT_SECRET' => $data['jwt_secret'],
        ];
        if (filled($data['db_password'] ?? null)) {
            $updates['DB_PASSWORD'] = $data['db_password'];
        }

        EnvFile::base()->set($updates);

        Notification::make()
            ->title('시스템 설정을 저장했습니다. 컨테이너를 재시작하면 적용됩니다.')
            ->success()
            ->send();

        $this->data['db_password'] = '';
    }

    protected function getHeaderActions(): array
    {
        return [
            Action::make('save')
                ->label('저장')
                ->action('save'),
        ];
    }
}
